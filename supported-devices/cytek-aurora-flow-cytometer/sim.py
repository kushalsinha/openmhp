"""Simulated twin of the SpectroFlo file route: a fake acquisition PC that consumes worklists and writes FCS 3.1 files."""
from __future__ import annotations

import csv
import importlib.util
import os
import pathlib
import random
import struct
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

EVENTS_PER_S = {"low": 800.0, "medium": 1600.0, "high": 3200.0}     # a typical lymphocyte prep at 15/30/60 uL/min
SETUP_S = 25.0                                                      # SIT lowering, boost, settle
SIM_EVENT_CAP = 100_000                                             # the twin writes at most this many events
CHANNELS = ["Time", "FSC-A", "FSC-H", "SSC-A", "SSC-B-A", "V1-A", "V3-A", "B2-A", "YG1-A", "R1-A"]


def write_fcs31(path: pathlib.Path, channels: list[str], events: int, keywords: dict) -> None:
    """A minimal conformant FCS 3.1 data set: HEADER (58 bytes), primary TEXT with the required keywords, DATA as
    little-endian single-precision floats ($DATATYPE/F/, $BYTEORD/1,2,3,4/, $MODE/L/, $PnB/32/, $PnE/0,0/)."""
    par = len(channels)
    data_len = events * par * 4
    delim = "/"
    def text_for(data_begin: int) -> bytes:
        kw = {"$BEGINANALYSIS": "0", "$ENDANALYSIS": "0", "$BEGINSTEXT": "0", "$ENDSTEXT": "0",
              "$BEGINDATA": str(data_begin), "$ENDDATA": str(data_begin + data_len - 1),
              "$BYTEORD": "1,2,3,4", "$DATATYPE": "F", "$MODE": "L", "$NEXTDATA": "0",
              "$PAR": str(par), "$TOT": str(events)}
        for n, name in enumerate(channels, 1):
            kw[f"$P{n}B"] = "32"; kw[f"$P{n}E"] = "0,0"; kw[f"$P{n}N"] = name; kw[f"$P{n}R"] = "4194304"
        kw.update(keywords)
        body = delim + "".join(f"{k}{delim}{v}{delim}" for k, v in kw.items())
        return body.encode("utf-8")
    # the TEXT length depends on the DATA offset it quotes; two passes settle it
    text_begin = 58
    data_begin = text_begin + len(text_for(10 ** 7)) + 2
    text = text_for(data_begin)
    data_begin = text_begin + len(text) + 2
    text = text_for(data_begin)
    text_end = text_begin + len(text) - 1
    header = (b"FCS3.1" + b" " * 4 + f"{text_begin:>8}{text_end:>8}{data_begin:>8}{data_begin + data_len - 1:>8}"
              f"{0:>8}{0:>8}".encode("ascii"))
    assert len(header) == 58
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        f.write(header); f.write(text); f.write(b"  ")
        pack = struct.Struct("<" + "f" * par)
        t = 0.0
        for _ in range(events):
            t += random.expovariate(1.0)
            vals = [t, random.gauss(150000, 30000), random.gauss(120000, 25000), random.gauss(80000, 40000),
                    random.gauss(60000, 30000)] + [abs(random.gauss(2000, 1500)) for _ in range(par - 5)]
            f.write(pack.pack(*vals[:par]))
        f.write(b"        ")                                       # no CRC: eight spaces (allowed by 3.1 section 3.5)
    tmp.replace(path)


class SimBackend(real.SpectroFloBackend):
    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.folders_ok = True
        self.hold = False                                  # True: nobody at the PC picks requests up
        self.sheath_ok = True
        self.due: dict[str, float] = {}

    def open(self) -> None:
        if not self.folders_ok:
            raise real.DeviceFault("simulated: the share with the SpectroFlo folders is unreachable",
                                   {"transient": True, "recovery": "retry_after"})
        for key in ("import_dir", "results_dir"):
            pathlib.Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        super().open()

    def sheath_level_ok(self):
        return self.sheath_ok

    def write_worklist(self, token: str, params: dict) -> str:
        path = super().write_worklist(token, params)
        rate = EVENTS_PER_S[params["flow_rate"]]
        by_events = min(int(params["stop_events"]), SIM_EVENT_CAP) / rate
        st = params.get("stop_time_s")
        seconds = SETUP_S + (min(by_events, float(st)) if st else by_events)
        self.due[token] = time.monotonic() + seconds * self.scale
        return path

    def poll(self) -> None:
        if self.hold:
            return
        for token, when in list(self.due.items()):
            if time.monotonic() < when:
                continue
            wl = pathlib.Path(self.cfg["import_dir"]) / f"{token}.csv"
            try:
                row = list(csv.DictReader(wl.read_text(encoding="utf-8").splitlines()))[0]
                self._export(token, row)
                wl.unlink()
            except OSError:                               # withdrawn: nobody acquired it
                pass
            del self.due[token]

    def _export(self, token: str, row: dict) -> None:
        rate = EVENTS_PER_S[row["Flow Rate"].lower()]
        wanted = min(int(row["Stop Events"]), SIM_EVENT_CAP)
        st = row.get("Stop Time (s)")
        events = min(wanted, int(float(st) * rate)) if st else wanted   # the first criterion met stops it
        out = pathlib.Path(self.cfg["results_dir"]) / f"{token}.fcs"
        write_fcs31(out, CHANNELS, events, {"$CYT": "Aurora (simulated)", "$FIL": out.name,
                                            "$SRC": row["Sample Name"], "TUBENAME": row["Sample Name"],
                                            "$DATE": time.strftime("%d-%b-%Y").upper(), "$BTIM": time.strftime("%H:%M:%S")})
        stats = pathlib.Path(self.cfg["results_dir"]) / f"{token}_stats.csv"
        live = int(events * random.gauss(0.92, 0.01))
        with stats.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Population", "Events", "% Parent", "Median FSC-A", "Median B2-A"])
            w.writerow(["All Events", events, "100.00", 150000, 2000])
            w.writerow(["Live", live, f"{100 * live / events:.2f}", 151000, 2100])
        self.log.append(f"export {out.name} ({events} events)")


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        root = home / "sim-data" / "cytek-aurora-flow-cytometer"
        self.cfg = {"import_dir": str(root / "worklists"), "results_dir": str(root / "export"),
                    "software": "SIM SpectroFlo 3", "allowed_templates": [], "result_wait_s": 3600, "poll_s": 10}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
