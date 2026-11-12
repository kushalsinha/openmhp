"""MHP driver for a Thermo Vanquish / UltiMate 3000 under Chromeleon 7.x through the Chromeleon SDK (pythonnet, Windows).

The SDK member names used are the ones visible in public code (IFPEN's PocSdkChromeleon and AllotropeConverters,
Thermo's SDK specification sheet); the ones marked `# unverified` were not seen anywhere public and must be
checked against the SDK reference on the first hardware test. See references/chromeleon_sdk.md. Every SDK call
sits behind ChromeleonBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
PEAK_FIELDS = (("name", "peak.name"), ("retention_min", "peak.retention_time"), ("area", "peak.area"), ("height", "peak.height"))
MAX_PEAKS = 200


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class ChromeleonBackend:
    """Thermo.Chromeleon.Sdk through pythonnet. 32-bit Python only: the SDK is x86 and raises
    SdkException "WrongArchitecture" from a 64-bit process."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.scope = self.factory = self.access = None
        self.ended: set[str] = set()

    def open(self) -> None:
        if not self.cfg.get("sdk_dir"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import sys
        if sys.maxsize > 2 ** 32:
            raise DeviceFault("the Chromeleon SDK is 32-bit; run this package under a 32-bit Python (SdkException WrongArchitecture otherwise)")
        import clr                                            # pythonnet
        clr.AddReference(str(pathlib.Path(self.cfg["sdk_dir"]) / "Thermo.Chromeleon.Sdk.dll"))
        clr.AddReference("System.Transactions")
        from Thermo.Chromeleon.Sdk.Common import CmSdk, CmSdkScope
        self._sdk, self._Uri = CmSdk, __import__("System").Uri
        self.scope = CmSdkScope()
        user = self.cfg.get("username")
        if user:
            try:
                import keyring
                pw = keyring.get_password("Chromeleon", user)
            except ImportError:
                pw = None
            CmSdk.Logon.DoLogon(user, pw)                     # unverified: DoLogon's credential overload
        else:
            CmSdk.Logon.DoLogon()                             # the interactive logon dialog, or the current session
        self.factory = CmSdk.GetItemFactory()
        self.access = CmSdk.GetInstrumentAccess()

    def _get(self, kind: str, url: str):
        from Thermo.Chromeleon.Sdk.Interfaces import Data
        typ = getattr(Data, kind)
        ok, item = self.factory.TryGetItem[typ](self._Uri(url), None)
        if not ok or item is None:
            raise DeviceFault(f"Chromeleon has no {kind} at {url}")
        return item

    def methods(self) -> dict:
        folder = self._get("IFolder", self.cfg["data_vault"])
        inst, proc = [], []
        for item in folder.Items:                             # unverified: IFolder's child collection name
            tn = type(item).__name__
            if "InstrumentMethod" in tn:
                inst.append(str(item.Name))
            elif "ProcessingMethod" in tn:
                proc.append(str(item.Name))
        return {"instrument_methods": sorted(inst), "processing_methods": sorted(proc)}

    def instrument(self):
        ok, inst = self.access.TryFindInstrument(self._Uri(self.cfg["instrument"]), None)
        if not ok or inst is None:
            raise DeviceFault(f"Chromeleon has no instrument at {self.cfg['instrument']}")
        return inst

    def status(self) -> dict:
        inst = self.instrument()
        state = getattr(inst, "State", None)                  # unverified: IInstrument.State
        return {"instrument": str(getattr(inst, "Name", self.cfg["instrument"])),
                "state": str(state) if state is not None else "unknown",
                "injections_ended": len(self.ended)}

    def create_sequence(self, name: str, lines: list[dict]) -> str:
        from System.Transactions import TransactionScope
        folder = self._get("IFolder", self.cfg["data_vault"])
        with TransactionScope() as tx:
            seq = self.factory.CreateSequence(name, folder)
            for i, l in enumerate(lines, 1):
                inj = self.factory.CreateInjection(l["name"], seq)
                inj.InstrumentMethodName.Value = l["instrument_method"]
                inj.ProcessingMethodName.Value = l["processing_method"]
                inj.InjectionVolume.Value = float(l["injection_volume_ul"])
                inj.Position.Value = l["vial"]                # unverified: the injection position/vial property
                inj.Comment.Value = l.get("comment") or ""
            for mname in {l["instrument_method"] for l in lines}:
                self._get("IInstrumentMethod", f"{self.cfg['data_vault'].rstrip('/')}/{mname}").CopyTo(seq, 0)   # CopyOptions.CurrentVersion
            for mname in {l["processing_method"] for l in lines}:
                self._get("IProcessingMethod", f"{self.cfg['data_vault'].rstrip('/')}/{mname}").CopyTo(seq, 0)
            tx.Complete()
        return str(seq.Url)

    def submit(self, seq_url: str) -> None:
        inst = self.instrument()
        inst.TakeControl()
        q = inst.QueueControl
        self.ended = set()
        q.InjectionRunEnded += lambda sender, args: self.ended.add(str(args.InjectionUri))
        q.AddItem(self._Uri(seq_url))
        q.ForceQueueStart()

    def sequence_done(self, seq_url: str, n_injections: int) -> bool:
        return len(self.ended) >= n_injections

    def results(self, seq_url: str, channel: str) -> list[dict]:
        seq = self._get("ISequence", seq_url)
        seq.Reload()
        out = []
        for inj in seq.Injections:
            peaks = []
            for k in range(1, MAX_PEAKS + 1):
                ctx = self.factory.CreateEvaluationContext(channel, k)
                row = {}
                for key, formula in PEAK_FIELDS:
                    r = inj.Evaluate(formula, ctx)
                    if r.IsError:
                        row = None
                        break
                    row[key] = float(r.NumericValue) if r.IsNumeric else str(r.StringValue)
                if row is None:
                    break
                peaks.append(row)
            out.append({"injection": str(inj.Name), "peaks": peaks})
        return out


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_busy = False
        self.last_result = None

    def make_backend(self):
        return ChromeleonBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"cannot open the Chromeleon SDK: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "instrument_status":
            try:
                return self._hw().status()
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"Chromeleon SDK status call failed: {type(e).__name__}: {e}", {"transient": True}) from None
        if name == "busy":
            return self.is_busy
        if name == "robot_access_ready":
            return not self.is_busy
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_samples":
            return
        samples = params["samples"]
        if not samples:
            raise InvalidValue("run_samples.samples must hold at least one sample")
        max_lines = int(self.cfg.get("max_lines", 96))
        total = sum(int(s.get("injections", 1)) for s in samples)
        if total > max_lines:
            raise LimitViolation(f"run_samples has {total} injections; the maximum is {max_lines}", {"max": max_lines})
        lo, hi = self.cfg.get("injection_volume_ul", [0.1, 100])
        allowed = self.cfg.get("allowed_methods") or []
        for i, s in enumerate(samples):
            if not lo <= s["injection_volume_ul"] <= hi:
                raise LimitViolation(f"samples[{i}].injection_volume_ul={s['injection_volume_ul']} outside this sampler's {lo}..{hi}", {"min": lo, "max": hi})
            if allowed and s["method"] not in allowed:
                raise InvalidValue(f"samples[{i}].method {s['method']!r} is not in allowed_methods")
            for key in ("name", "vial", "method"):
                if "/" in s[key] or "\\" in s[key]:
                    raise InvalidValue(f"samples[{i}].{key} may not contain a path separator")
        if "/" in (params.get("sequence_name") or "") or "\\" in (params.get("sequence_name") or ""):
            raise InvalidValue("run_samples.sequence_name must be a plain name")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "list_methods":
            try:
                return hw.methods()
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"listing methods failed: {type(e).__name__}: {e}") from None
        if job.action != "run_samples":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        status = hw.status()
        if str(status.get("state", "")).lower() not in ("idle", "ready", "unknown"):
            raise DeviceFault(f"{self.cfg.get('instrument')} is not idle: {status}")
        name = p.get("sequence_name") or f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        proc_default = p.get("processing_method") or self.cfg.get("processing_method") or ""
        lines = [{"name": s["name"] if n == 0 else f"{s['name']}_{n + 1}", "vial": s["vial"],
                  "injection_volume_ul": float(s["injection_volume_ul"]), "instrument_method": s["method"],
                  "processing_method": s.get("processing_method") or proc_default, "comment": f"OpenMHP job {job.id}"}
                 for s in p["samples"] for n in range(int(s.get("injections", 1)))]
        started = time.time()
        try:
            seq_url = hw.create_sequence(name, lines)
            hw.submit(seq_url)
        except DeviceFault:
            raise
        except Exception as e:                                # noqa: BLE001
            raise DeviceFault(f"creating or queueing sequence {name} failed: {type(e).__name__}: {e}") from None
        self.is_busy = True
        scale = self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * scale
        limit = float(self.cfg.get("max_run_hours", 24)) * 3600 * scale
        t0 = time.monotonic()
        try:
            while True:
                self.checkpoint(job, min(0.98, len(hw.ended) / max(1, len(lines))), phase="acquiring")
                if hw.sequence_done(seq_url, len(lines)):
                    break
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"sequence {name} still running after {self.cfg.get('max_run_hours', 24)} h")
                status = hw.status()
                self.emit_signal("instrument_status", status)
                time.sleep(poll)
            status = hw.status()
            try:
                results = hw.results(seq_url, p["channel"])
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"reading results of {name} failed: {type(e).__name__}: {e}") from None
        finally:
            self.is_busy = False
        result = {"sequence_name": name, "sequence_url": seq_url, "injections": len(lines), "samples": len(p["samples"]),
                  "final_status": status, "elapsed_s": round((time.time() - started) / scale, 1), "results": results}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    # ---- setup-time checks (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        dll = pathlib.Path(cfg.get("sdk_dir") or "") / "Thermo.Chromeleon.Sdk.dll"
        if not dll.is_file():
            raise DeviceFault(f"{dll} not found; it ships in the Chromeleon bin folder of a client install with an SDK licence")
        hw = ChromeleonBackend(cfg)
        try:
            hw.open()
        except ImportError:
            raise DeviceFault("pythonnet is not installed (pip install pythonnet)") from None
        status = hw.status()
        return f"Chromeleon SDK answers; instrument {status.get('instrument')} is {status.get('state')}"

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "methods" and cfg.get("sdk_dir") and cfg.get("data_vault"):
            hw = ChromeleonBackend(cfg)
            hw.open()
            return hw.methods().get("instrument_methods", [])
        return []
