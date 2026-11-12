"""MHP driver for an LC-MS sample queue built as a vendor import file (file-based route).

The package never talks to a mass spectrometer. It writes the sample list / batch / worklist /
sequence file that the vendor acquisition software imports (Waters MassLynx, SCIEX OS, Agilent
MassHunter Acquisition, Thermo Xcalibur), in the folder config.json names, and reads it back to
report the rows. Starting the acquisition is a person's click in the vendor software.

Column names and conventions are documented in references/worklist_formats.md; every format
detail that could not be verified against a vendor document is marked there.
"""
from __future__ import annotations

import csv
import io
import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job

HERE = pathlib.Path(__file__).parent
VENDORS = ("masslynx", "sciexos", "masshunter", "xcalibur")
SAMPLE_TYPES = ("sample", "standard", "blank", "qc")

# vendor -> (file extension, column header in order, sample-type words, newline, encoding)
FORMATS = {
    "masslynx": {
        "ext": ".csv",
        "columns": ["FILE_NAME", "FILE_TEXT", "MS_FILE", "MS_TUNE_FILE", "INLET_FILE", "SAMPLE_LOCATION",
                    "TYPE", "ID", "INJ_VOL", "Index"],
        "types": {"sample": "Analyte", "standard": "Standard", "blank": "Blank", "qc": "QC"},
        "encoding": "utf-8",
    },
    "sciexos": {
        "ext": ".txt",
        "columns": ["Sample Name", "Sample ID", "Sample Type", "MS Method", "LC Method", "Rack Type",
                    "Rack Position", "Plate Type", "Plate Position", "Vial Position", "Injection Volume",
                    "Data File", "Processing Method", "Comment"],
        "types": {"sample": "Unknown", "standard": "Standard", "blank": "Blank", "qc": "QualityControl"},
        "encoding": "utf-8",
    },
    "masshunter": {
        "ext": ".csv",
        "columns": ["Sample Name", "Barcode", "Rack Code", "Sample Position", "Method", "Data File",
                    "Sample Type", "Level Name", "Inj Vol (µL)", "Comment"],
        "types": {"sample": "Sample", "standard": "Calibration", "blank": "Blank", "qc": "QC"},
        "encoding": "utf-8-sig",                      # Agilent: save as UTF-8 when the header carries a micro sign
    },
    "xcalibur": {
        "ext": ".csv",
        "columns": ["Sample Type", "File Name", "Sample ID", "Path", "Instrument Method", "Process Method",
                    "Calibration File", "Position", "Inj Vol", "Level", "Sample Wt", "Sample Vol", "ISTD Amt",
                    "Dil Factor", "L1 Study", "L2 Client", "L3 Laboratory", "L4 Company", "L5 Phone", "Comment",
                    "Sample Name"],
        "types": {"sample": "Unknown", "standard": "Std Bracket", "blank": "Blank", "qc": "QC"},
        "encoding": "utf-8",
    },
}
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def safe_name(text: str) -> str:
    """A file-name-safe version of a sample name (Windows-forbidden characters become '_')."""
    out = _BAD_NAME.sub("_", text).strip(" .")
    return out or "sample"


def fmt_num(v: float) -> str:
    return f"{v:g}"


class WorklistBackend:
    """Owns the four file formats. `write` renders and writes; `read_back` parses the file written."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []

    # ---- folders ------------------------------------------------------------------------ #
    def output_dir(self) -> pathlib.Path:
        d = self.cfg.get("output_dir")
        if not d:
            raise DeviceFault("config.json is missing output_dir (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        return pathlib.Path(d)

    def open(self) -> None:
        v = self.cfg.get("vendor")
        if v not in VENDORS:
            raise DeviceFault(f"config.json vendor must be one of {list(VENDORS)}, got {v!r}",
                              {"transient": False, "recovery": "operator"})
        d = self.output_dir()
        if not d.is_dir():
            raise DeviceFault(f"output folder {d} does not exist", {"transient": True, "recovery": "operator"})
        if not os.access(d, os.W_OK):
            raise DeviceFault(f"output folder {d} is not writable", {"transient": True, "recovery": "operator"})

    # ---- rendering ---------------------------------------------------------------------- #
    def rows(self, vendor: str, samples: list[dict], token: str) -> list[list[str]]:
        spec = FORMATS[vendor]
        out = []
        for i, s in enumerate(samples, 1):
            data_file = s.get("data_file") or f"{token}_{i:03d}_{safe_name(s['name'])}"
            typ = spec["types"][s.get("sample_type") or "sample"]
            vol = fmt_num(float(s["injection_volume_ul"]))
            ms, lc = s["ms_method"], s.get("lc_method") or ""
            if vendor == "masslynx":
                row = [data_file, s["name"], ms, self.cfg.get("tune_file") or "", lc, s["position"], typ,
                       s["name"], vol, str(i)]
            elif vendor == "sciexos":
                row = [s["name"], s["name"], typ, ms, lc, "", "", "", "", s["position"], vol, data_file, "", ""]
            elif vendor == "masshunter":
                df = data_file if data_file.lower().endswith(".d") else data_file + ".d"
                row = [s["name"], "", "", s["position"], ms, df, typ, "", vol, ""]
            else:                                                     # xcalibur
                row = [typ, data_file, s["name"], self.cfg.get("data_path") or "", ms, "", "", s["position"], vol,
                       "", "0", "0", "0", "1", "", "", "", "", "", "", s["name"]]
            out.append(row)
        return out

    def render(self, vendor: str, samples: list[dict], token: str) -> str:
        spec = FORMATS[vendor]
        delim = ";" if (vendor == "xcalibur" and self.cfg.get("list_separator") == ";") else ","
        buf = io.StringIO()
        if vendor == "xcalibur":
            buf.write(f"Bracket Type={int(self.cfg.get('bracket_type', 4))}\r\n")
        w = csv.writer(buf, delimiter=delim, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
        w.writerow(spec["columns"])
        for row in self.rows(vendor, samples, token):
            w.writerow(row)
        return buf.getvalue()

    def write(self, vendor: str, samples: list[dict], token: str, name: str | None) -> pathlib.Path:
        d = self.output_dir()
        path = d / (safe_name(name or f"mhp_{token}") + FORMATS[vendor]["ext"])
        if path.exists():
            raise InvalidValue(f"{path.name} already exists in {d}; choose another worklist_name",
                               {"file": str(path)})
        text = self.render(vendor, samples, token)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(text.encode(FORMATS[vendor]["encoding"]))
        os.replace(tmp, path)
        self.log.append(f"wrote {path.name} ({len(samples)} rows, {vendor})")
        return path

    def read_back(self, vendor: str, path: pathlib.Path) -> list[dict]:
        """Parse the file written, the way a vendor import would see it: header row then rows."""
        text = path.read_bytes().decode("utf-8-sig")
        lines = text.splitlines()
        if vendor == "xcalibur":
            if not lines or not lines[0].startswith("Bracket Type="):
                raise DeviceFault("Xcalibur sequence must start with 'Bracket Type=n'", {"transient": False})
            lines = lines[1:]
        delim = ";" if (vendor == "xcalibur" and self.cfg.get("list_separator") == ";") else ","
        return list(csv.DictReader(lines, delimiter=delim))

    def abort(self) -> None:
        self.log.append("estop: nothing runs here; worklist files already written are left in place")


class LCMSWorklist(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_worklist: str | None = None

    def make_backend(self):
        return WorklistBackend(self.cfg)

    def _hw(self) -> WorklistBackend:
        if self.hw is None:
            hw = self.make_backend()
            hw.open()                                  # raises DeviceFault with a plain reason
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "vendor":
            return str(self.cfg.get("vendor") or "")
        if name == "last_worklist":
            return self.last_worklist
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "build_worklist":
            return
        samples = params.get("samples") or []
        if not isinstance(samples, list):
            raise InvalidValue("build_worklist.samples must be a list")
        max_rows = int(self.cfg.get("max_rows", 384))
        if len(samples) > max_rows:
            raise InvalidValue(f"build_worklist has {len(samples)} samples; the maximum is {max_rows}",
                               {"max": max_rows})
        seen_files: set[str] = set()
        for i, s in enumerate(samples):
            for k in ("name", "position"):
                if not str(s.get(k, "")).strip():
                    raise InvalidValue(f"samples[{i}].{k} must be a non-empty string")
            ms = s.get("ms_method") or params.get("ms_method")
            if not ms:
                raise InvalidValue(f"samples[{i}].ms_method is missing and no top-level ms_method default was given")
            df = s.get("data_file")
            if df:
                if _BAD_NAME.search(df):
                    raise InvalidValue(f"samples[{i}].data_file {df!r} contains a character a data file name may not")
                if df.lower() in seen_files:
                    raise InvalidValue(f"samples[{i}].data_file {df!r} is used twice; data file names must be unique")
                seen_files.add(df.lower())
        name = params.get("worklist_name")
        if name is not None and (_BAD_NAME.search(name) or not name.strip()):
            raise InvalidValue("worklist_name contains a character a file name may not")

    def on_invoke(self, job: Job):
        if job.action != "build_worklist":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        samples = p.get("samples") or []
        if not samples:
            raise InvalidValue("build_worklist needs at least one sample (a method carries the defaults; "
                               "pass the samples as params)")
        vendor = self.cfg["vendor"]
        filled = []
        for s in samples:
            row = dict(s)
            row["ms_method"] = row.get("ms_method") or p.get("ms_method")
            if row.get("lc_method") is None:
                row["lc_method"] = p.get("lc_method")
            filled.append(row)
        token = f"{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        self.checkpoint(job, 0.2, phase="rendering")
        path = hw.write(vendor, filled, token, p.get("worklist_name"))
        self.checkpoint(job, 0.8, phase="reading back")
        rows = hw.read_back(vendor, path)
        if len(rows) != len(filled):
            raise DeviceFault(f"wrote {len(filled)} rows but read back {len(rows)} from {path.name}",
                              {"transient": False, "recovery": "operator"})
        self.last_worklist = str(path)
        self.emit_signal("last_worklist", self.last_worklist)
        return {"vendor": vendor, "file": str(path), "rows": len(rows), "samples": len(filled)}

    def on_estop(self) -> None:
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "vendor":
            return [("masslynx", "Waters MassLynx 4.x sample list (.csv)"), ("sciexos", "SCIEX OS batch (.txt)"),
                    ("masshunter", "Agilent MassHunter Acquisition worklist (.csv)"),
                    ("xcalibur", "Thermo Xcalibur sequence (.csv)")]
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = WorklistBackend(cfg)
        hw.open()
        return f"{cfg.get('vendor')} worklists will be written to {cfg.get('output_dir')} (folder exists and is writable)"
