"""Human-operated instrument.

The descriptor is real and the safety gates are real, but the hands are a person's.

* A setting write records a *request* and asks the operator; it does not claim the
  instrument was set. Reads return only values an operator reported.
* An action waits in state ``waiting_operator`` until a person acknowledges it
  through the ``acknowledge`` action. ``wait()`` therefore does not advance a
  protocol before the work is done.
* ``record`` stores a reading the operator reports. Both ``record`` and
  ``acknowledge`` require a person's confirmation, so a model cannot fabricate
  completion or measurements.
* Emergency stop is a request to the operator; it is not an automatic stop, and a
  manual device never claims a watchdog.
"""
from __future__ import annotations

import threading
import time

from ..driver import Driver, InvalidValue, Job, check_type

OPERATOR_ACTIONS = [
    {"name": "acknowledge", "duration": "short", "approval": "confirm", "concurrent": True,
     "params": {"job": "id of the job the operator finished", "done": "true if completed, false if not",
                "notes": "optional remarks from the operator"},
     "required": ["job"],
     "notes": "A person confirms that they carried out a pending operator instruction."},
    {"name": "record", "duration": "short", "approval": "confirm", "concurrent": True,
     "params": {"signal": "name of a signal", "value": "what the operator read off the instrument"},
     "required": ["signal", "value"],
     "notes": "Store a reading a person reports from the instrument display."},
]


class ManualDriver(Driver):
    def setup(self):
        self.requested: dict[str, tuple[object, float]] = {}
        self.observed: dict[str, tuple[object, float]] = {}
        self.values = self.observed                           # backward-compatible name
        self._acks: dict[str, tuple[threading.Event, dict]] = {}
        names = {a["name"] for a in self.descriptor.get("actions", [])}
        extra = [dict(a) for a in OPERATOR_ACTIONS if a["name"] not in names]
        if extra:
            self.descriptor = {**self.descriptor, "actions": [*self.descriptor.get("actions", []), *extra]}
            self._reindex()

    def on_read(self, name):
        v = self.observed.get(name)
        return v[0] if v else None

    def on_write(self, name, value):
        self.requested[name] = (value, time.time())
        self.notify("operator/instruction", {"text": f"Please set {name} to {value} on the instrument."})
        return {"applied": False, "requested": True,
                "note": "a person must set this on the instrument; it is not confirmed until they report it"}

    def validate_params(self, action: str, params: dict) -> None:
        if action == "record":
            spec = self._index["signals"].get(params.get("signal"))
            if spec is None:
                raise InvalidValue(f"record: unknown signal {params.get('signal')!r}")
            check_type(f"record.{spec['name']}", spec.get("type", "number"), params.get("value"))
        if action == "acknowledge":
            jid = params.get("job")
            if jid not in self._acks:
                raise InvalidValue(f"acknowledge: job {jid!r} is not waiting for an operator")
            if "done" in params and not isinstance(params["done"], bool):
                raise InvalidValue("acknowledge: done must be true or false")

    def on_invoke(self, job: Job):
        if job.action == "record":
            sig, val = job.params["signal"], job.params["value"]
            self.observed[sig] = (val, time.time())
            return {"recorded": {sig: val}, "source": "operator"}
        if job.action == "acknowledge":
            ev, payload = self._acks[job.params["job"]]
            payload.update(done=job.params.get("done", True), notes=job.params.get("notes"), by=job.owner, at=time.time())
            ev.set()
            return {"acknowledged": job.params["job"], "done": payload["done"]}
        text = (f"Operator: please perform '{job.action}'" + (f" with {job.params}" if job.params else "") +
                ". A person must confirm completion (acknowledge).")
        ev, payload = threading.Event(), {}
        self._acks[job.id] = (ev, payload)
        with self._state_lock:
            job.state, job.waiting = "waiting_operator", text
        self.notify("operator/instruction", {"text": text, "job": job.id})
        try:
            while not ev.wait(0.2):
                self.checkpoint(job)
        finally:
            self._acks.pop(job.id, None)
        if not payload.get("done", True):
            raise RuntimeError(f"operator reported '{job.action}' was not completed: {payload.get('notes') or 'no notes'}")
        return {"completed_by": "operator", "notes": payload.get("notes")}

    def on_estop(self):
        self.notify("operator/instruction", {"text": "EMERGENCY STOP requested: stop the instrument now."})

    def verify_recovery(self):
        return True, "operator-run instrument: recovery is the operator's call"
