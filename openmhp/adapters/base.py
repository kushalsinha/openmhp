"""Bindings: the few-lines way to put any controllable thing behind MHP.

An adapter author describes a device as three small lists of *bindings*, each
pairing an MHP name with a callable into the underlying control layer. The
BoundDriver turns them into a full MHP driver with every safety gate, the
detail tiers, jobs and notifications inherited from Driver.

    dev = BoundDriver(
        device={"id": "hotplate-01", "class": "hotplate", "notes": "Fume hood 2."},
        signals=[Signal("plate_temperature", read=lambda: plc.read(0x10), unit="degC")],
        settings=[Setting("target_temperature", write=lambda v: plc.write(0x20, v),
                          unit="degC", limits={"min": 20, "max": 300})],
        actions=[Action("shutdown", run=lambda job, p: plc.write(0x21, 0), approval="confirm")],
        estop=lambda: plc.write(0x21, 0),
    )

Ecosystem adapters (sila2, pylabrobot, madsci, opcua, ros2) are just functions
that build these bindings by introspecting their layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..driver import Driver, Job


@dataclass
class Signal:
    name: str
    read: Callable[[], Any]
    type: str = "number"
    unit: str | None = None
    notes: str | None = None

    def spec(self) -> dict:
        return _clean({"name": self.name, "type": self.type, "unit": self.unit, "notes": self.notes})


@dataclass
class Setting:
    name: str
    write: Callable[[Any], None]
    read: Callable[[], Any] | None = None
    type: str = "number"
    unit: str | None = None
    limits: dict | None = None
    approval: str = "auto"
    interlocks: list[str] = field(default_factory=list)
    during_job: bool = False
    notes: str | None = None

    def spec(self) -> dict:
        return _clean({"name": self.name, "type": self.type, "unit": self.unit, "limits": self.limits,
                       "approval": self.approval, "interlocks": self.interlocks or None,
                       "during_job": self.during_job or None, "notes": self.notes})


@dataclass
class Action:
    name: str
    run: Callable[[Job, dict], Any]          # run(job, params) -> result; may call driver.checkpoint(job, x)
    duration: str = "short"
    approval: str = "auto"
    interlocks: list[str] = field(default_factory=list)
    params: dict | None = None
    required: list[str] | None = None
    limits: dict | None = None               # {param: [min, max] | {min, max} | {enum: [...]}}, enforced by the driver
    validate: Callable[[dict], None] | None = None   # side-effect-free whole-request check (dry runs and real runs)
    examples: list[dict] | None = None
    concurrent: bool = False
    pausable: bool = False                   # True only if run() calls driver.checkpoint between steps
    cancellable: bool = True                 # False when the backend cannot stop mid-run safely
    notes: str | None = None

    def spec(self) -> dict:
        return _clean({"name": self.name, "duration": self.duration, "approval": self.approval,
                       "interlocks": self.interlocks or None, "params": self.params, "required": self.required,
                       "limits": self.limits, "examples": self.examples, "concurrent": self.concurrent or None,
                       "pausable": self.pausable or None, "cancellable": None if self.cancellable else False,
                       "notes": self.notes})


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


class BoundDriver(Driver):
    """A Driver assembled from bindings. Works with every transport and the directory."""

    def __init__(self, device: dict, signals: list[Signal] = (), settings: list[Setting] = (),
                 actions: list[Action] = (), *, physical: dict | None = None, safety: dict | None = None,
                 estop: Callable[[], None] | None = None, setup: Callable[[], None] | None = None,
                 extra: dict | None = None):
        self._signals = {s.name: s for s in signals}
        self._settings = {s.name: s for s in settings}
        self._actions = {a.name: a for a in actions}
        self._estop_fn, self._setup_fn = estop, setup
        interlocks = sorted({i for b in [*settings, *actions] for i in b.interlocks})
        self.descriptor = {
            "device": device,
            "physical": physical or {},
            "signals": [s.spec() for s in signals],
            "settings": [s.spec() for s in settings],
            "actions": [a.spec() for a in actions],
            "safety": {"estop": estop is not None, "interlocks": interlocks, **(safety or {})},
            **(extra or {}),
        }
        super().__init__()

    def setup(self):
        if self._setup_fn:
            self._setup_fn()

    def on_read(self, name):
        if name in self._signals:
            return self._signals[name].read()
        s = self._settings.get(name)
        if s and s.read:
            return s.read()
        raise KeyError(name)

    def on_write(self, name, value):
        return self._settings[name].write(value)

    def validate_params(self, action: str, params: dict) -> None:
        a = self._actions.get(action)
        if a is not None and a.validate is not None:
            a.validate(params)

    def on_invoke(self, job: Job):
        return self._actions[job.action].run(job, job.params)

    def on_estop(self):
        if self._estop_fn:
            self._estop_fn()


def params_from_signature(fn: Callable, skip: tuple[str, ...] = ("self",)) -> dict:
    """Best-effort MHP `params` doc from a Python signature."""
    import inspect
    out = {}
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return out
    for n, p in sig.parameters.items():
        if n in skip or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = "" if p.annotation is inspect._empty else getattr(p.annotation, "__name__", str(p.annotation))
        dflt = "" if p.default is inspect._empty else f" (default {p.default!r})"
        out[n] = (ann + dflt).strip() or "any"
    return out
