"""MHP driver for a Global FIA FloPro Sampler through FloZF's general serial device.

FloZF polls this package over a virtual serial pair (see references/flozf_server_sequence.md).
`handle_line` is the whole protocol; the transport (pyserial here, a fake FloZF in sim.py) only
moves lines.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class SerialTransport:
    def __init__(self, cfg: dict, handle):
        self.cfg, self.handle = cfg, handle

    def open(self) -> None:
        if not self.cfg.get("port"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import serial
        self.ser = serial.Serial(self.cfg["port"], int(self.cfg.get("baud", 9600)), timeout=0.5)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        buf = b""
        while True:
            chunk = self.ser.read(64)
            if not chunk:
                continue
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                reply = self.handle(line.decode("ascii", "replace").strip())
                if reply is not None:
                    self.ser.write((reply + "\r").encode("ascii"))


class FloProSampler(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.transport = None
        self.lock = threading.Lock()
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.last_poll = 0.0
        self.leave = False
        self.stopped = False                               # e-stop latched: answer nothing, so FloZF aborts
        self.vials: list[int] = []
        self.last_sample = None

    def make_transport(self):
        return SerialTransport(self.cfg, self.handle_line)

    def time_scale(self) -> float:
        return 1.0

    def _ensure(self) -> None:
        if self.transport is None:
            t = self.make_transport()
            try:
                t.open()
            except Exception as e:                         # noqa: BLE001
                raise DeviceFault(f"cannot open the FloZF serial link: {type(e).__name__}: {e}") from None
            self.transport = t

    # ---- the protocol FloZF speaks ------------------------------------------------------------
    def handle_line(self, line: str) -> str | None:
        word, _, arg = line.partition(" ")
        word = word.upper()
        with self.lock:
            if self.stopped:
                return None                                # FloZF's step times out, it aborts and runs its stop sequence
            if word == "CHECK":
                return "OK"
            if word == "POLL":
                self.last_poll = time.monotonic()
                if self.current is None and self.queue:
                    self.current = self.queue.pop(0)
                    self.current["picked_at"] = time.time()
                    return str(self.current["code"])
                if self.current is None and self.leave:
                    self.leave = False
                    return "-1"
                return "0"
            if word == "GET":
                if self.current is None:
                    return "0"
                return str(self.current["numbers"].get(arg.strip().lower(), 0))
            if word in ("DONE", "ABORTED"):
                if self.current is not None:
                    self.current["outcome"] = "done" if word == "DONE" else "aborted"
                    self.current["event"].set()
                    self.current = None
                return "OK"
        return "?"

    # ---- MHP ------------------------------------------------------------------------------
    def on_read(self, name: str):
        if name == "connected":
            try:
                self._ensure()
            except DeviceFault:
                return False
            window = 3 * float(self.cfg.get("poll_s", 2)) * self.time_scale() + 1
            return time.monotonic() - self.last_poll < window
        if name == "busy":
            return self.current is not None
        if name == "vials_used":
            return list(self.vials)
        if name == "last_sample":
            return self.last_sample
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "take_sample":
            return
        if params.get("destination") == "archive":
            vial = params.get("vial")
            if not isinstance(vial, int) or isinstance(vial, bool):
                raise InvalidValue("take_sample.vial is required for destination archive")
            if vial in self.vials:
                raise InvalidValue(f"archive vial {vial} already holds a sample from this session")
        if params.get("destination") not in (self.cfg.get("sequence_codes") or {}):
            raise InvalidValue(f"FloZF has no sequence code for destination {params.get('destination')!r}")

    def _run(self, job: Job, code: int, numbers: dict) -> dict:
        self._ensure()
        entry = {"code": code, "numbers": numbers, "event": threading.Event(), "job": job.id}
        with self.lock:
            self.queue.append(entry)
        pickup = float(self.cfg.get("pickup_timeout_s", 60)) * self.time_scale()
        finish = float(self.cfg.get("sequence_timeout_s", 900)) * self.time_scale()
        t0 = time.monotonic()
        while "picked_at" not in entry:
            try:
                self.checkpoint(job, phase="waiting for FloZF")
            except JobCancelled:
                with self.lock:
                    if entry in self.queue:
                        self.queue.remove(entry)
                        raise
                break                                          # already picked up: cannot cancel, see it through
            if time.monotonic() - t0 > pickup:
                with self.lock:
                    if entry in self.queue:
                        self.queue.remove(entry)
                raise DeviceFault("FloZF did not pick up the job; is the mhp_server sequence running?")
            time.sleep(0.05)
        t1 = time.monotonic()
        while not entry["event"].wait(0.2):
            self.progress(job, min(0.95, (time.monotonic() - t1) / finish), phase="FloZF sequence running")
            if time.monotonic() - t1 > finish:
                with self.lock:
                    self.current = None
                raise DeviceFault("FloZF picked up the job but did not report DONE in time; a person must check the sampler")
        if entry["outcome"] == "estop":
            raise DeviceFault("emergency stop: FloZF aborts at its next CHECK step and runs its stop sequence")
        if entry["outcome"] != "done":
            raise DeviceFault("FloZF reported the sequence ABORTED; a person must check the sampler")
        return {"started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry["picked_at"])),
                "duration_s": round((time.monotonic() - t1) / self.time_scale(), 1)}

    def on_estop(self) -> None:
        with self.lock:
            self.stopped = True
            self.queue.clear()
            if self.current is not None:
                self.current["outcome"] = "estop"
                self.current["event"].set()
                self.current = None

    def verify_recovery(self):
        with self.lock:
            self.stopped = False                           # a person restarted mhp_server in FloZF
        return super().verify_recovery()

    def on_invoke(self, job: Job):
        codes = self.cfg.get("sequence_codes") or {}
        if job.action == "stop_server":
            self._ensure()
            self.leave = True
            return {"requested": True}
        if job.action == "rinse":
            if "rinse" not in codes:
                raise InvalidValue("no rinse sequence code in config.json")
            return {"rinse": True, **self._run(job, int(codes["rinse"]), {})}
        if job.action != "take_sample":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        numbers = {"probe": int(p["probe"]), "dil1": float(p["dilution_1"]), "dil2": float(p["dilution_2"]),
                   "vial": int(p.get("vial") or 0)}
        out = self._run(job, int(codes[p["destination"]]), numbers)
        if p["destination"] == "archive":
            self.vials.append(numbers["vial"])
            self.emit_signal("vials_used", list(self.vials))
        sample = {"label": p.get("label"), "destination": p["destination"], "probe": numbers["probe"],
                  "dilution_total": numbers["dil1"] * numbers["dil2"], "vial": numbers["vial"] or None, **out}
        self.last_sample = sample
        self.emit_signal("last_sample", sample)
        return sample
