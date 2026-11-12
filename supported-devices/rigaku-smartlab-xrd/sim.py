"""Simulated twin of the SmartLab Studio II route: a fake import flow that takes the job after a moment and, once
the scaled scan time has passed, writes both a `.ras` text file (header block and angle/intensity/attenuation rows)
and a `.rasx` zip (root.xml, Data0/Profile0.txt, Data0/MesurementConditions0.xml) of a powder pattern."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import tempfile
import time
import zipfile

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

PEAKS = [(12.4, 900), (17.9, 1400), (21.3, 650), (25.6, 2600), (28.1, 480), (31.7, 1100), (38.2, 300), (44.6, 420), (56.1, 260)]
TUBE = {"target": "Cu", "kv": 40, "ma": 30}


def pattern(two_theta: float) -> float:
    bg = 60 + 20 * math.exp(-two_theta / 15)
    s = sum(h * math.exp(-0.5 * ((two_theta - c) / 0.07) ** 2) for c, h in PEAKS)
    return max(0.0, random.gauss(bg + s, math.sqrt(bg + s)))


class SimBackend(real.StudioBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}

    def write_job(self, token, p, result_name):
        path = super().write_job(token, p, result_name)
        prog = p["program"]
        n = real.RigakuSmartLab._points(prog)
        now = time.monotonic()
        minutes = (prog["end_2theta"] - prog["start_2theta"]) / prog["speed_deg_min"]
        self.jobs[token] = {"p": p, "n": n, "result_name": result_name, "path": path,
                            "read_at": now + 3 * self.scale, "done_at": now + (90 + minutes * 60) * self.scale}
        return path

    def _tick(self):
        now = time.monotonic()
        for token, j in list(self.jobs.items()):
            if now >= j["read_at"] and j["path"].exists():
                j["path"].unlink()
            if now >= j["done_at"]:
                self._write_result(j)
                self.jobs.pop(token)

    def picked_up(self, token):
        self._tick()
        return super().picked_up(token)

    def result_path(self, result_name):
        self._tick()
        return super().result_path(result_name)

    def _write_result(self, j):
        prog, n, p = j["p"]["program"], j["n"], j["p"]
        pts = [(prog["start_2theta"] + i * prog["step"], pattern(prog["start_2theta"] + i * prog["step"])) for i in range(n)]
        header = [("*DISP_LINE_COLOR", "0"), ("*FILE_PACKAGE_NAME", "openmhp"), ("*FILE_PART_ID", "GeneralMeasurement(BB)"),
                  ("*FILE_SAMPLE", p["sample_id"]), ("*FILE_TYPE", "RAS_RAW"), ("*FILE_VERSION", "1"),
                  ("*HW_XG_TARGET_NAME", TUBE["target"]), ("*HW_XG_WAVE_LENGTH_ALPHA1", "1.540593"),
                  ("*HW_XG_WAVE_LENGTH_ALPHA2", "1.544414"), ("*HW_XG_WAVE_LENGTH_UNIT", "Angstrom"),
                  ("*MEAS_COND_XG_CURRENT", str(TUBE["ma"])), ("*MEAS_COND_XG_VOLTAGE", str(TUBE["kv"])),
                  ("*MEAS_COND_XG_WAVE_TYPE", "Ka"), ("*MEAS_DATA_COUNT", str(n)),
                  ("*MEAS_SCAN_AXIS_X", prog.get("axis", "TwoThetaTheta")), ("*MEAS_SCAN_AXIS_X_INTERNAL", prog.get("axis", "TwoThetaTheta")),
                  ("*MEAS_SCAN_MODE", str(prog.get("mode", "continuous")).upper()),
                  ("*MEAS_SCAN_SPEED", f"{prog['speed_deg_min']:.4f}"), ("*MEAS_SCAN_SPEED_UNIT", "deg/min"),
                  ("*MEAS_SCAN_START", f"{prog['start_2theta']:.4f}"), ("*MEAS_SCAN_STEP", f"{prog['step']:.4f}"),
                  ("*MEAS_SCAN_STOP", f"{prog['end_2theta']:.4f}"), ("*MEAS_SCAN_UNEQUALY_SPACED", "False"),
                  ("*MEAS_SCAN_UNIT_X", "deg"), ("*MEAS_SCAN_UNIT_Y", "counts")]
        out = pathlib.Path(self.cfg["results_dir"])
        # .ras: ASCII, CRLF, header keys with quoted values, three-column rows
        ras = ["*RAS_DATA_START", "*RAS_HEADER_START"] + [f'{k} "{v}"' for k, v in header] + ["*RAS_HEADER_END", "*RAS_INT_START"]
        ras += [f"{a:.4f} {c:.4f} 1.0000" for a, c in pts] + ["*RAS_INT_END", "*RAS_DATA_END"]
        (out / (j["result_name"] + ".ras")).write_bytes(("\r\n".join(ras) + "\r\n").encode("ascii", errors="replace"))
        # .rasx: zip with Profile0.txt (BOM, tab-separated) and the conditions XML (vendor spelling kept)
        profile = "﻿" + "".join(f"{a:.4f}\t{c:.11g}\t1\r\n" for a, c in pts)
        pairs = "".join(f"<Pair><string>{k}</string><string>{v}</string></Pair>" for k, v in header)
        cond = ('﻿<?xml version="1.0" encoding="utf-8"?>\n<MeasurementConditions>\n'
                f'<GeneralInformation><SampleName>{p["sample_id"]}</SampleName><SystemName>SmartLab</SystemName>'
                '<PackageName>openmhp</PackageName><PartName>GeneralMeasurement</PartName><Type>RAS_RAW</Type></GeneralInformation>\n'
                f'<HWConfigurations><XrayGenerator><TargetName>{TUBE["target"]}</TargetName><Voltage>{TUBE["kv"]}</Voltage><VoltageUnit>kV</VoltageUnit>'
                f'<Current>{TUBE["ma"]}</Current><CurrentUnit>mA</CurrentUnit><WaveType>Ka1</WaveType><WavelengthKalpha1>1.540593</WavelengthKalpha1></XrayGenerator></HWConfigurations>\n'
                f'<ScanInformation><AxisName>{prog.get("axis", "TwoThetaTheta")}</AxisName><Mode>{str(prog.get("mode", "continuous")).upper()}</Mode>'
                f'<Start>{prog["start_2theta"]:.4f}</Start><Stop>{prog["end_2theta"]:.4f}</Stop><Step>{prog["step"]:.4f}</Step>'
                f'<Speed>{prog["speed_deg_min"]:.4f}</Speed><SpeedUnit>deg/min</SpeedUnit><PositionUnit>deg</PositionUnit>'
                f'<IntensityUnit>counts</IntensityUnit><DataCount>{n}</DataCount></ScanInformation>\n'
                f'<RASHeader>{pairs}</RASHeader>\n</MeasurementConditions>\n')
        tmp = out / (j["result_name"] + ".rasx.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("root.xml", '﻿<?xml version="1.0" encoding="utf-8"?><Root Version="1.1.0.0"><Data0 Type="Profile"/></Root>')
            z.writestr("Data0/Profile0.txt", profile.encode("utf-8"))
            z.writestr("Data0/MesurementConditions0.xml", cond.encode("utf-8"))
        os.replace(tmp, out / (j["result_name"] + ".rasx"))
        self.log.append(f"result {j['result_name']}.rasx and .ras written ({n} points)")


class SimRigakuSmartLab(real.RigakuSmartLab):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="rigaku-smartlab-xrd-", dir=base))
        for d in ("jobs", "results"):
            (root / d).mkdir()
        self.cfg = {"job_dir": str(root / "jobs"), "results_dir": str(root / "results"), "changer_positions": 10,
                    "changer_s": 90, "max_points": 50000, "max_scan_hours": 12, "poll_s": 10, "result_wait_s": 7200}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
