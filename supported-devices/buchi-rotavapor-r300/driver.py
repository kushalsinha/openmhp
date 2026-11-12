"""MHP driver for a Büchi Rotavapor R-300 with Interface I-300 Pro through the BUCHI OpenInterface (REST/JSON).

Endpoints and field names follow Büchi's published OpenAPI spec (R300_openinterface.yaml, "BUCHI R-300
OpenInterface" 1.0.0); see references/openinterface.md. The HTTP client sits behind RotavaporBackend so the
simulated twin can replace it.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
LIFT_DOWN_MM = 220                      # lift.set is 0 (up) or 220 (down) on the I-300 Pro; multipleOf 220
STOP_PATCH = {"globalStatus": {"running": False}, "heating": {"running": False}, "rotation": {"running": False},
              "vacuum": {"aerateValveOpen": True}, "lift": {"set": 0}}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class RotavaporBackend:
    """Basic-auth HTTPS client for /api/v1 on the I-300 Pro. Only the stdlib: no vendor package exists."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import base64
        import ssl
        try:
            import keyring
            password = keyring.get_password("BuchiRotavapor", str(self.cfg["host"]))
        except ImportError:
            raise DeviceFault("the keyring package is not installed (pip install keyring); the OpenInterface password lives there") from None
        if not password:
            raise DeviceFault(f"no OpenInterface password in the keyring for BuchiRotavapor / {self.cfg['host']} "
                              f"(python -m keyring set BuchiRotavapor {self.cfg['host']})")
        user = self.cfg.get("user", "rw")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.ctx = ssl.create_default_context()
        if self.cfg.get("verify_tls") is False:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        elif self.cfg.get("ca_cert"):
            self.ctx.load_verify_locations(self.cfg["ca_cert"])
        self.base = f"https://{self.cfg['host']}/api/v1"
        self.info()

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        import urllib.error
        import urllib.request
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": self.auth, "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.get("timeout_s", 10)), context=self.ctx) as r:
                text = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            transient = e.code in (503,)
            raise DeviceFault(f"OpenInterface {method} {path} answered {e.code}: {detail or e.reason}",
                              {"transient": transient, "status": e.code}) from None
        except (urllib.error.URLError, OSError) as e:
            raise DeviceFault(f"cannot reach the I-300 Pro at {self.cfg['host']}: {e}", {"transient": True}) from None
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            raise DeviceFault(f"OpenInterface {method} {path} answered non-JSON: {text[:120]!r}") from None

    def info(self) -> dict:
        return self._req("GET", "/info")

    def process(self) -> dict:
        return self._req("GET", "/process")

    def patch(self, body: dict) -> dict:
        return self._req("PUT", "/process", body)


def lift_word(act) -> str:
    if not isinstance(act, (int, float)):
        return "unknown"
    if act <= 5:
        return "up"
    if act >= LIFT_DOWN_MM - 5:
        return "down"
    return "moving"


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_running = False
        self.last_result = None

    def make_backend(self):
        return RotavaporBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"cannot open the OpenInterface: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _process(self) -> dict:
        p = self._hw().process()
        if not isinstance(p, dict):
            raise DeviceFault("GET /process did not answer an object")
        return p

    @staticmethod
    def _num(section: dict | None, key: str):
        v = (section or {}).get(key)
        return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "busy":
            return self.is_running
        if name == "last_result":
            return self.last_result
        p = self._process()
        if name == "bath_temperature":
            v = self._num(p.get("heating"), "act")
            if v is None:
                raise DeviceFault("heating.act is missing from /process")
            return v
        if name == "vapor_temperature":
            return self._num(p.get("vacuum"), "vaporTemp")
        if name == "rotation_rpm":
            v = self._num(p.get("rotation"), "act")
            return v if v is not None else 0.0
        if name == "vacuum_mbar":
            v = self._num(p.get("vacuum"), "act")
            if v is None:
                raise DeviceFault("vacuum.act is missing from /process (is the VacuBox connected?)")
            return v
        if name == "cooling_temperature":
            return self._num(p.get("cooling"), "act")
        if name == "lift_position":
            return lift_word((p.get("lift") or {}).get("act"))
        if name == "running":
            return bool((p.get("globalStatus") or {}).get("running"))
        if name == "heating_on":
            return bool((p.get("heating") or {}).get("running"))
        if name == "process_status":
            return dict(p.get("globalStatus") or {})
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        hw = self._hw()
        field = {"bath_setpoint": "heating", "rotation_setpoint": "rotation", "vacuum_setpoint": "vacuum",
                 "cooling_setpoint": "cooling"}.get(name)
        if field is None:
            raise InvalidValue(f"unknown setting {name}")
        hw.patch({field: {"set": value}})
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action == "evaporate":
            if params["bath_c"] < 5 and params.get("cooling_c") is not None and params["cooling_c"] > params["bath_c"]:
                raise InvalidValue("evaporate: cooling_c above bath_c would condense nothing")
            if params["vacuum_mbar"] > 1000 and params["duration_min"] > 1:
                raise InvalidValue("evaporate: vacuum_mbar above 1000 mbar is atmospheric; nothing distils")

    def _snapshot(self) -> dict:
        p = self._process()
        return {"bath_c": self._num(p.get("heating"), "act"), "vapor_c": self._num(p.get("vacuum"), "vaporTemp"),
                "rotation_rpm": self._num(p.get("rotation"), "act"), "vacuum_mbar": self._num(p.get("vacuum"), "act"),
                "cooling_c": self._num(p.get("cooling"), "act"), "lift": lift_word((p.get("lift") or {}).get("act")),
                "running": bool((p.get("globalStatus") or {}).get("running")),
                "error": (p.get("globalStatus") or {}).get("currentError")}

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "start":
            hw.patch({"rotation": {"running": True}, "heating": {"running": True},
                      "vacuum": {"aerateValveOpen": False}, "globalStatus": {"running": True}})
            return self._snapshot()
        if job.action == "stop":
            hw.patch({"globalStatus": {"running": False}, "rotation": {"running": False}, "heating": {"running": False}})
            return self._snapshot()
        if job.action == "vent":
            hw.patch({"vacuum": {"aerateValveOpen": True}})
            return self._snapshot()
        if job.action == "lift_up":
            hw.patch({"lift": {"set": 0}})
            return self._snapshot()
        if job.action == "lift_down":
            hw.patch({"lift": {"set": LIFT_DOWN_MM}})
            return self._snapshot()
        if job.action != "evaporate":
            raise InvalidValue(f"unhandled action {job.action}")

        p = job.params
        scale = self.time_scale()
        started = time.time()
        patch = {"heating": {"set": p["bath_c"], "running": True}, "rotation": {"set": p["rotation_rpm"], "running": True},
                 "vacuum": {"set": p["vacuum_mbar"], "aerateValveOpen": False}, "lift": {"set": LIFT_DOWN_MM},
                 "globalStatus": {"running": True}}
        if p.get("cooling_c") is not None:
            patch["cooling"] = {"set": p["cooling_c"], "running": True}
        hw.patch(patch)
        self.is_running = True
        duration = float(p["duration_min"]) * 60 * scale
        poll = min(1.0, max(0.02, duration / 50))
        t0, snap = time.monotonic(), {}
        try:
            while True:
                try:
                    self.checkpoint(job, min(0.99, (time.monotonic() - t0) / duration), phase="distilling")
                except JobCancelled:
                    hw.patch(STOP_PATCH)
                    raise
                snap = self._snapshot()
                if snap.get("error"):
                    raise DeviceFault(f"the I-300 Pro reports error {snap['error']} during evaporate; a person must check it")
                vapor, stop_below = snap.get("vapor_c"), p.get("stop_when_vapor_below_c")
                if stop_below is not None and vapor is not None and vapor < stop_below and time.monotonic() - t0 > 60 * scale:
                    break
                if time.monotonic() - t0 >= duration:
                    break
                time.sleep(poll)
        finally:
            self.is_running = False
        hw.patch({"globalStatus": {"running": False}, "heating": {"running": p["keep_bath_warm"]},
                  "rotation": {"running": False}, "vacuum": {"aerateValveOpen": True}, "lift": {"set": 0}})
        t1 = time.monotonic()
        final = self._snapshot()
        while final["lift"] != "up" and time.monotonic() - t1 < 60 * scale:   # the lift takes a few seconds
            time.sleep(poll)
            final = self._snapshot()
        result = {"duration_s": round((time.time() - started) / scale, 1), "final_vacuum_mbar": snap.get("vacuum_mbar") or 0.0,
                  "final_bath_c": snap.get("bath_c") or 0.0, "final_vapor_c": snap.get("vapor_c"),
                  "stopped_by": "vapor_temperature" if (p.get("stop_when_vapor_below_c") is not None and time.monotonic() - t0 < duration) else "time",
                  "final": final}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.patch(STOP_PATCH)
        except Exception:                                # noqa: BLE001  must not raise
            pass
        self.is_running = False

    # ---- setup-time check (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = RotavaporBackend(cfg)
        hw.open()
        info = hw.info()
        ctl = info.get("controller") or {}
        return (f"{info.get('systemClass', 'Rotavapor')} {info.get('systemName', '')} at {cfg.get('host')} answers; "
                f"controller {ctl.get('model', '?')} firmware {ctl.get('firmware', '?')}")
