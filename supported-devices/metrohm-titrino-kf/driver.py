"""MHP driver for Metrohm Karl Fischer Titrinos over their RS-232 remote-control protocol.

Two dialects, chosen by config.json `dialect`:
  plus     870 KF Titrino plus (and the 8xx "plus" family through the 6.2148.030 RS-232/USB box, COM2):
           synchronous `$G`, `$S`, `$H`, `$D`, `$L(method)`, `$Q(variable)`; answers OK / E1 / E2 / E3.
           Source: 870 KF Titrino plus manual 8.870.8003EN, chapter 10.7.
  classic  758 KFD / 784 KFP / 787 KF Titrino and other 7xx Titrinos: the object tree (`&Mode $G`,
           `&UserMeth.Recall "name"`, `&SmplData.OFFSilo.ValSmpl "1.2345"`, `&Info.TitrResults...$Q`, `$D`).
           Source: 758 KFD Titrino manual 8.758.1203, chapter 3; 784 KFP 8.784.1003.
See references/rs232.md. The serial port sits behind TitrinoLink so the simulated twin can replace it.
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, NotSupported

HERE = pathlib.Path(__file__).parent
STATUS_WORDS = ("Ready", "Busy", "Hold", "Cond")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def parse_number(text: str):
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text or "")
    return float(m.group(0)) if m else None


class TitrinoLink:
    """pyserial behind one `ask` call: write a line, read the one-line answer."""

    def __init__(self, cfg: dict):
        self.cfg, self.port = cfg, None

    def open(self) -> None:
        if not self.cfg.get("port"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        try:
            import serial
        except ImportError:
            raise DeviceFault("pyserial is not installed (pip install pyserial)") from None
        baud = int(self.cfg.get("baud", 19200 if self.cfg.get("dialect", "plus") == "plus" else 9600))
        try:
            self.port = serial.Serial(self.cfg["port"], baudrate=baud, bytesize=8, parity="N", stopbits=1,
                                      timeout=float(self.cfg.get("timeout_s", 2)), xonxoff=True)
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"cannot open {self.cfg['port']}: {type(e).__name__}: {e}", {"transient": True}) from None

    def ask(self, cmd: str) -> str:
        try:
            self.port.reset_input_buffer()
            self.port.write((cmd + "\r\n").encode("ascii"))
            raw = self.port.readline()
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"serial I/O failed on {cmd!r}: {type(e).__name__}: {e}", {"transient": True}) from None
        if not raw:
            raise DeviceFault(f"no answer to {cmd!r} within the timeout; check the cable, baud and that COM2 (RS-232/2) is the remote port", {"transient": True})
        return raw.decode("ascii", errors="replace").strip()

    def close(self) -> None:
        try:
            if self.port is not None:
                self.port.close()
        except Exception:                                        # noqa: BLE001
            pass


class Plus:
    """870 KF Titrino plus remote control (manual 8.870.8003EN, 10.7)."""

    def __init__(self, link: TitrinoLink):
        self.link = link

    def _ok(self, cmd: str) -> str:
        a = self.link.ask(cmd)
        if a.startswith("E1"):
            raise InvalidValue(f"{cmd}: E1, method not found (the name must exist and be unique)")
        if a.startswith("E2"):
            raise DeviceFault(f"{cmd}: E2, invalid variable")
        if a.startswith("E3"):
            raise DeviceFault(f"{cmd}: E3, invalid command")
        return a

    def start(self): self._ok("$G")
    def stop(self): self._ok("$S")
    def hold(self): self._ok("$H")

    def status(self) -> dict:
        a = self.link.ask("$D")
        word = next((w for w in STATUS_WORDS if w.lower() in a.lower()), "unknown")
        nums = re.findall(r"\d+", a)
        return {"status": word, "message": int(nums[-1]) if nums else 0, "raw": a}

    def load_method(self, name: str): self._ok(f"$L({name})")

    def query(self, var: str):
        return parse_number(self._ok(f"$Q({var})"))

    def set_sample(self, mass_g: float):
        raise NotSupported("the Titrino plus remote protocol documents no command to enter the sample size; "
                           "set the method to a fixed sample size or a balance input (dialect classic can write it)")

    def result(self) -> dict:
        return {"result": self.query("R1"), "end_volume_ml": self.query("MCV"), "duration_s": self.query("DD"),
                "sample_size": self.query("C00"), "drift": None}


class Classic:
    """7xx Titrino object-tree protocol (758 KFD manual 8.758.1203, chapter 3)."""

    def __init__(self, link: TitrinoLink, titer_mg_ml: float):
        self.link, self.titer = link, titer_mg_ml

    def _check(self, cmd: str) -> str:
        a = self.link.ask(cmd)
        m = re.search(r"E(\d+)", a)
        if m and m.group(1) not in ("26", "27", "33"):
            raise DeviceFault(f"{cmd}: Titrino error E{m.group(1)} ({a})")
        return a

    def start(self): self._check("&Mode $G")
    def stop(self): self._check("&Mode $S")
    def hold(self): self._check("&Mode $H")

    def status(self) -> dict:
        a = self.link.ask("$D")
        low = a.lower()
        if "$g" in low:
            word = "Busy"
        elif "$h" in low:
            word = "Hold"
        elif ".cond" in low:
            word = "Cond"
        elif "$r" in low or "$s" in low:
            word = "Ready"
        else:
            word = "unknown"
        m = re.search(r"E(\d+)", a)
        return {"status": word, "message": int(m.group(1)) if m else 0, "raw": a, "conditioned": ".cond.ok" in low}

    def load_method(self, name: str): self._check(f'&UserMeth.Recall "{name}"')

    def set_sample(self, mass_g: float): self._check(f'&SmplData.OFFSilo.ValSmpl "{mass_g:.4f}"')

    def _q(self, path: str):
        return parse_number(self._check(f"{path} $Q"))

    def result(self) -> dict:
        drift_ul_min = self._q("&Info.TitrResults.Var.C43")
        return {"result": self._q("&Info.TitrResults.RS.1.Value"), "end_volume_ml": self._q("&Info.TitrResults.Var.C41"),
                "duration_s": self._q("&Info.TitrResults.Var.C42"), "sample_size": None,
                "drift": None if drift_ul_min is None else round(drift_ul_min * self.titer, 2)}


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.proto = None
        self.is_busy = False
        self.sample_mass_g = None
        self.last = None

    def make_link(self):
        return TitrinoLink(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _proto(self):
        if self.proto is None:
            link = self.make_link()
            try:
                link.open()
            except DeviceFault:
                raise
            except Exception as e:                                # noqa: BLE001
                raise DeviceFault(f"cannot open the Titrino's port: {type(e).__name__}: {e}") from None
            self.hw = link
            dialect = self.cfg.get("dialect", "plus")
            self.proto = Plus(link) if dialect == "plus" else Classic(link, float(self.cfg.get("titer_mg_ml", 5.0)))
            self.proto.status()                                   # proves the instrument answers
        return self.proto

    def _conditioned(self, st: dict) -> bool:
        if st.get("status") != "Cond":
            return False
        if "conditioned" in st:
            return bool(st["conditioned"])
        return st.get("message", 0) == 0

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._proto()
                return True
            except DeviceFault:
                return False
        if name == "busy":
            return self.is_busy
        if name == "sample_mass_g":
            return self.sample_mass_g
        if name == "last_result":
            return self.last
        if name in ("water_content", "water_content_ppm", "water_mg", "titrant_consumption_ml", "drift_ug_min"):
            if not self.last:
                return None
            unit = self.last.get("result_unit")
            if name == "water_content":
                return self.last.get("result")
            if name == "water_content_ppm":
                return self.last.get("result") if unit == "ppm" else None
            if name == "water_mg":
                return self.last.get("result") if unit == "mg" else None
            if name == "titrant_consumption_ml":
                return self.last.get("titrant_ml")
            return self.last.get("drift_ug_min")
        st = self._proto().status()
        if name == "titrator_status":
            return st["status"]
        if name == "cell_conditioned":
            return self._conditioned(st)
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "sample_mass_g":
            raise InvalidValue(f"unknown setting {name}")
        proto = self._proto()
        if isinstance(proto, Classic):
            proto.set_sample(float(value))
        self.sample_mass_g = float(value)
        return {"note": "stored for the next determination" if isinstance(proto, Plus) else "written to SmplData.OFFSilo.ValSmpl"}

    def validate_params(self, action: str, params: dict) -> None:
        if action == "determine":
            if not re.fullmatch(r"[A-Za-z0-9 _.\-]{1,12}", params["method"]):
                raise InvalidValue("determine.method must be a Titrino method name (letters, digits, space, _ . -, up to 12 characters)")
            if params.get("sample_mass_g") is None and self.sample_mass_g is None and params["result_unit"] != "mg":
                raise InvalidValue("determine: give sample_mass_g (or write the sample_mass_g setting first) for a ppm or % result")

    def _begin_conditioning(self, proto) -> None:
        """A KF Titrino that reads Ready has its method stopped; one start begins conditioning the cell."""
        if proto.status()["status"] == "Ready":
            proto.start()

    def _wait(self, job: Job, proto, until, phase: str, timeout_s: float, f0: float, f1: float) -> dict:
        scale = self.time_scale()
        t0 = time.monotonic()
        poll = max(0.02, min(2.0, 2 * scale))
        while True:
            st = proto.status()
            self.emit_signal("titrator_status", st["status"])
            if until(st):
                return st
            elapsed = (time.monotonic() - t0) / scale
            try:
                self.checkpoint(job, f0 + (f1 - f0) * min(0.95, elapsed / timeout_s), phase=phase, status=st["status"])
            except JobCancelled:
                proto.stop()
                raise
            if elapsed > timeout_s:
                raise DeviceFault(f"still {st['status']} after {timeout_s:.0f} s during {phase} (message {st['message']})")
            time.sleep(poll)

    def on_invoke(self, job: Job):
        proto = self._proto()
        p = job.params
        if job.action == "stop":
            proto.stop()
            return {"status": proto.status()["status"]}

        if job.action == "condition":
            self.is_busy = True
            try:
                self._begin_conditioning(proto)
                st = self._wait(job, proto, self._conditioned, "conditioning", p["timeout_min"] * 60, 0.0, 0.98)
            finally:
                self.is_busy = False
            return {"conditioned": True, "status": st["status"]}

        if job.action != "determine":
            raise InvalidValue(f"unhandled action {job.action}")
        started = time.time()
        mass = p.get("sample_mass_g") if p.get("sample_mass_g") is not None else self.sample_mass_g
        proto.load_method(p["method"])
        if isinstance(proto, Classic) and mass is not None:
            proto.set_sample(float(mass))
        self.is_busy = True
        try:
            if p["wait_for_conditioning"]:
                self._begin_conditioning(proto)
                self._wait(job, proto, self._conditioned, "conditioning", p["timeout_min"] * 60, 0.0, 0.2)
            proto.start()
            self._wait(job, proto, lambda s: s["status"] in ("Busy", "Hold"), "starting", 60, 0.2, 0.25)
            st = self._wait(job, proto, lambda s: s["status"] in ("Ready", "Cond"), "titrating", p["timeout_min"] * 60, 0.25, 0.95)
            if st.get("message"):
                raise DeviceFault(f"the Titrino shows message {st['message']} after the determination; a person must acknowledge it")
            raw = proto.result()
        finally:
            self.is_busy = False
        result = {"method": p["method"], "result_unit": p["result_unit"], "result": raw.get("result"),
                  "water_content_ppm": raw.get("result") if p["result_unit"] == "ppm" else None,
                  "water_mg": raw.get("result") if p["result_unit"] == "mg" else None,
                  "titrant_ml": raw.get("end_volume_ml"), "drift_ug_min": raw.get("drift"),
                  "sample_mass_g": float(mass) if mass is not None else None,
                  "duration_s": round((time.time() - started) / self.time_scale(), 1), "sample_id": p.get("sample_id")}
        self.last = result
        self.sample_mass_g = None                                  # one determination per entered mass
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.proto is not None:
                self.proto.stop()
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.is_busy = False

    # ---- setup-time checks (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "port":
            try:
                from serial.tools import list_ports
                return [(p.device, p.description) for p in list_ports.comports()]
            except ImportError:
                return []
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        link = TitrinoLink(cfg)
        link.open()
        try:
            a = link.ask("$D")
        finally:
            link.close()
        return f"Titrino on {cfg.get('port')} answers $D with {a!r}"
