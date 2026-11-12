"""Opentrons OT-2 through PyLabRobot's OT-2 backend, as MHP bindings (the openmhp.adapters.pylabrobot shape).

Same shape as supported-devices/opentrons-flex and hamilton-star: `Backend` holds every PyLabRobot
call and imports the library only at setup, `Machine` resolves deck resource names and keeps a busy
flag. PyLabRobot does not surface the OT-2's door switch, but the robot's HTTP API does
(GET /robot/door/status on port 31950, robot-server `robot/control/router.py`), so `door_open` is read
there and `robot_access_ready` is built from it. No gripper, so no move_plate.

Requires on the controlling PC: pip install pylabrobot (network access to the OT-2 on port 31950).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import urllib.request

from openmhp.adapters import Action, BoundDriver, Setting, Signal
from openmhp.adapters.pylabrobot import _Loop, params_from_signature
from openmhp.driver import DeviceFault, InvalidValue, LimitViolation

HERE = pathlib.Path(__file__).parent
ACTIONS = ["pick_up_tips", "drop_tips", "aspirate", "dispense"]


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class Backend:
    """Every PyLabRobot call plus the one HTTP call for the door. build() imports the library."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def build(self):
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        from pylabrobot.liquid_handling import LiquidHandler
        try:
            from pylabrobot.liquid_handling.backends import OpentronsOT2Backend as OpentronsBackend
        except ImportError:                                      # releases before the rename
            from pylabrobot.liquid_handling.backends import OpentronsBackend
        from pylabrobot.resources import Deck
        from pylabrobot.resources.opentrons import OTDeck
        path = pathlib.Path(self.cfg.get("deck_file") or "")
        deck = Deck.load_from_json_file(str(path)) if path.is_file() else OTDeck()   # unverified: load_from_json_file
        return LiquidHandler(backend=OpentronsBackend(host=self.cfg["host"], port=int(self.cfg.get("port", 31950))), deck=deck)

    def door_open(self) -> bool:
        url = f"http://{self.cfg.get('host')}:{int(self.cfg.get('port', 31950))}/robot/door/status"
        req = urllib.request.Request(url, headers={"Opentrons-Version": "*"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                doc = json.loads(r.read())
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"cannot read the OT-2 door state at {url}: {type(e).__name__}: {e}", {"transient": True}) from None
        return str((doc.get("data") or {}).get("status", "")).lower() == "open"


class Machine:
    """The PyLabRobot LiquidHandler behind name resolution and a busy flag; built by Backend.build()."""

    def __init__(self, backend):
        self.backend, self.lh, self.loop = backend, None, None
        self.setup_finished, self.error, self.busy = False, None, False
        self.volume_cap = float(getattr(backend, 'cfg', {}).get('volume_cap', 1000))

    async def setup(self):
        self.loop = asyncio.get_running_loop()
        try:
            self.lh = self.backend.build()
            await self.lh.setup()
            self.setup_finished, self.error = True, None
        except ImportError:
            self.error = "pylabrobot is not installed (pip install pylabrobot)"
        except DeviceFault as e:
            self.error = e.message
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            self.error = f"OT-2 setup failed: {type(e).__name__}: {e}"

    async def stop(self):
        if self.lh is not None and self.setup_finished:
            try:
                await self.lh.stop()                             # cancels the HTTP-API run: the robot halts
            finally:
                self.setup_finished = False

    def _lh(self):
        if not self.setup_finished or self.lh is None:
            raise DeviceFault(self.error or "the OT-2 is not set up", {"transient": True})
        return self.lh

    def _resource(self, name: str):
        if not isinstance(name, str) or not name:
            raise InvalidValue(f"resource name must be a non-empty string, got {name!r}")
        try:
            return self._lh().deck.get_resource(name)
        except DeviceFault:
            raise
        except Exception:                                        # noqa: BLE001  ResourceNotFoundError
            raise InvalidValue(f"no resource {name!r} on the deck; names come from the deck layout file") from None

    def _item(self, ref: str):
        if "/" not in str(ref):
            return self._resource(ref)
        parent, well = str(ref).rsplit("/", 1)
        try:
            return self._resource(parent).get_item(well)
        except (InvalidValue, DeviceFault):
            raise
        except Exception:                                        # noqa: BLE001
            raise InvalidValue(f"{parent!r} has no position {well!r}") from None

    async def _run(self, coro):
        self.busy = True
        try:
            return await coro
        except (InvalidValue, DeviceFault):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"OT-2: {type(e).__name__}: {e}") from None
        finally:
            self.busy = False

    async def pick_up_tips(self, tip_spots: list):
        """Pick up tips from the named tip spots ('tips_300/A1'); 8 spots for the 8-channel pipette."""
        lh = self._lh()
        return await self._run(lh.pick_up_tips([self._item(s) for s in tip_spots], ))

    async def drop_tips(self, tip_spots: list):
        """Drop tips into the named spots or the fixed trash ('trash')."""
        lh = self._lh()
        return await self._run(lh.drop_tips([self._item(s) for s in tip_spots], ))

    async def aspirate(self, resources: list, vols: list, flow_rate: float | None = None):
        """Aspirate vols (uL) from the named wells ('plate/A1')."""
        lh = self._lh()
        return await self._run(lh.aspirate([self._item(r) for r in resources], vols=[float(v) for v in vols],
                                           flow_rates=None if flow_rate is None else [float(flow_rate)] * len(resources)))

    async def dispense(self, resources: list, vols: list, flow_rate: float | None = None):
        """Dispense vols (uL) into the named wells."""
        lh = self._lh()
        return await self._run(lh.dispense([self._item(r) for r in resources], vols=[float(v) for v in vols],
                                           flow_rates=None if flow_rate is None else [float(flow_rate)] * len(resources)))

    def door_open(self) -> bool | None:
        try:
            return bool(self.backend.door_open())
        except DeviceFault:
            return None


NAMES = {"pick_up_tips": ("tip_spots",), "drop_tips": ("tip_spots",), "aspirate": ("resources",),
         "dispense": ("resources",)}


def _validator(machine: Machine, names: tuple):
    """Side-effect-free: resolves every named resource on the deck model and checks volumes against the
    cap before anything moves (dry runs too)."""
    def validate(params: dict):
        if "vols" in params:
            if len(params["vols"]) != len(params.get("resources") or []):
                raise InvalidValue("vols must have one entry per resource")
            over = [v for v in params["vols"] if v > machine.volume_cap]
            if over:
                raise LimitViolation(f"vols {over} above volume_cap {machine.volume_cap} uL (the tip or pipette mounted)",
                                     {"min": 0, "max": machine.volume_cap})
        if not machine.setup_finished:
            return                                               # the connected interlock refuses it anyway
        for key in names:
            for ref in (params.get(key) if isinstance(params.get(key), list) else [params.get(key)]):
                if ref is not None:
                    machine._item(ref)
    return validate


def build(machine: Machine) -> BoundDriver:
    """The same assembly openmhp.adapters.pylabrobot.plr_device does (one private event loop, one action per
    coroutine, stop() as the e-stop), plus the signals, the volume_cap setting and the validators."""
    loop = _Loop()

    def make_action(name):
        fn = getattr(machine, name)

        def run(job, params):
            res = loop.run(fn(**params), timeout=1800)
            return res if isinstance(res, (dict, list, str, int, float, bool, type(None))) else str(res)
        return Action(name, run=run, duration="long", params=params_from_signature(fn) or None, cancellable=False,
                      validate=_validator(machine, NAMES[name]), notes=(inspect.getdoc(fn) or "").split("\n")[0] or None)

    def access_ready():
        if machine.busy or not machine.setup_finished:
            return False
        return machine.door_open() is True

    def set_cap(v):
        machine.volume_cap = float(v)

    signals = [
        Signal("connected", read=lambda: bool(machine.setup_finished), type="boolean"),
        Signal("connect_error", read=lambda: machine.error, type="string"),
        Signal("setup_finished", read=lambda: bool(machine.setup_finished), type="boolean"),
        Signal("door_open", read=machine.door_open, type="boolean"),
        Signal("door_closed", read=lambda: machine.door_open() is False, type="boolean"),
        Signal("robot_access_ready", read=access_ready, type="boolean"),
    ]
    settings = [Setting("volume_cap", write=set_cap, read=lambda: machine.volume_cap, unit="uL",
                        limits={"min": 1, "max": 1000})]
    return BoundDriver(device={}, signals=signals, settings=settings, actions=[make_action(n) for n in ACTIONS],
                       estop=lambda: loop.run(machine.stop(), timeout=30), setup=lambda: loop.run(machine.setup()),
                       extra={"pylabrobot": {"machine": "LiquidHandler", "backend": "OpentronsOT2Backend"}})


def Device():
    return build(Machine(Backend(load_config())))


def probe(cfg: dict) -> str:
    try:
        import pylabrobot                                        # noqa: F401
    except ImportError:
        raise DeviceFault("pylabrobot is not installed (pip install pylabrobot)") from None
    door = Backend(cfg).door_open()
    return f"OT-2 at {cfg.get('host')} answers on port {cfg.get('port', 31950)}; door {'open' if door else 'closed'}"


Device.probe = probe                                             # noqa: E305  mhp node setup looks here
