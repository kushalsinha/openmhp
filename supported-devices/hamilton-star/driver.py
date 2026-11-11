"""Hamilton Microlab STAR / STARlet / Vantage through PyLabRobot, as MHP bindings (the openmhp.adapters.pylabrobot shape).

`Backend` holds every PyLabRobot call and imports it only when the device is set up, so the package
loads on a laptop without pylabrobot and `connected` then reads False with the reason. `Machine` is
what the adapter sees: the LiquidHandler coroutines with deck resources named as strings
("tips_1000/A1", "src_plate/A1", "dst_site"), a busy flag, and the STAR front-cover sensor read
through `STARBackend.request_cover_open()`, which is what `robot_access_ready` is built from.

Requires on the real instrument: pip install pylabrobot (USB access to the STAR; Hamilton's own
software must not hold the instrument).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib

from openmhp.adapters import Action, BoundDriver, Setting, Signal
from openmhp.adapters.pylabrobot import _Loop, params_from_signature
from openmhp.driver import DeviceFault, InvalidValue, LimitViolation

HERE = pathlib.Path(__file__).parent
ACTIONS = ["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate"]


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class Backend:
    """Every PyLabRobot call. build() imports the library; nothing else in this file does."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def build(self):
        if not self.cfg.get("deck_file"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        from pylabrobot.liquid_handling import LiquidHandler
        from pylabrobot.liquid_handling.backends import STAR
        from pylabrobot.resources import Deck, STARDeck, STARLetDeck
        path = pathlib.Path(self.cfg["deck_file"])
        if path.is_file():
            deck = Deck.load_from_json_file(str(path))                         # unverified: Resource.load_from_json_file
        else:
            deck = STARDeck() if str(self.cfg.get("deck", "STARlet")).upper() == "STAR" else STARLetDeck()
        kw = {k: self.cfg[k] for k in ("device_address", "serial_number") if self.cfg.get(k) is not None}
        return LiquidHandler(backend=STAR(**kw), deck=deck)


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
            self.error = f"STAR setup failed: {type(e).__name__}: {e}"

    async def stop(self):
        if self.lh is not None and self.setup_finished:
            try:
                await self.lh.stop()
            finally:
                self.setup_finished = False

    # ---- names -> resources ------------------------------------------------------------------
    def _lh(self):
        if not self.setup_finished or self.lh is None:
            raise DeviceFault(self.error or "the STAR is not set up", {"transient": True})
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
        """'rack/A1' -> the TipSpot or Well; a bare name -> the resource itself (a trash, a site)."""
        if "/" not in str(ref):
            return self._resource(ref)
        parent, well = str(ref).rsplit("/", 1)
        try:
            return self._resource(parent).get_item(well)
        except (InvalidValue, DeviceFault):
            raise
        except Exception:                                        # noqa: BLE001  IndexError / KeyError
            raise InvalidValue(f"{parent!r} has no position {well!r}") from None

    async def _run(self, coro):
        self.busy = True
        try:
            return await coro
        except (InvalidValue, DeviceFault):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"STAR: {type(e).__name__}: {e}") from None
        finally:
            self.busy = False

    # ---- the actions (signatures document the params; descriptor.yaml bounds them) ------------
    async def pick_up_tips(self, tip_spots: list):
        """Pick up tips from the named tip spots ('rack/A1'), one per channel."""
        lh = self._lh()
        return await self._run(lh.pick_up_tips([self._item(s) for s in tip_spots], ))

    async def drop_tips(self, tip_spots: list):
        """Drop tips into the named tip spots or the trash ('trash')."""
        lh = self._lh()
        return await self._run(lh.drop_tips([self._item(s) for s in tip_spots], ))

    async def aspirate(self, resources: list, vols: list, flow_rate: float | None = None):
        """Aspirate vols (uL) from the named wells ('plate/A1'), one per channel."""
        lh = self._lh()
        return await self._run(lh.aspirate([self._item(r) for r in resources], vols=[float(v) for v in vols],
                                           flow_rates=None if flow_rate is None else [float(flow_rate)] * len(resources)))

    async def dispense(self, resources: list, vols: list, flow_rate: float | None = None):
        """Dispense vols (uL) into the named wells, one per channel."""
        lh = self._lh()
        return await self._run(lh.dispense([self._item(r) for r in resources], vols=[float(v) for v in vols],
                                           flow_rates=None if flow_rate is None else [float(flow_rate)] * len(resources)))

    async def move_plate(self, plate: str, to: str):
        """Move a plate with the iSWAP / CO-RE gripper to a named site."""
        lh = self._lh()
        return await self._run(lh.move_plate(self._resource(plate), self._resource(to)))

    # ---- the cover sensor --------------------------------------------------------------------
    async def cover_open(self) -> bool | None:
        lh = self._lh()
        try:
            return bool(await lh.backend.request_cover_open())
        except Exception:                                        # noqa: BLE001  no cover monitoring installed
            return None

    def cover_open_now(self) -> bool | None:
        if not self.setup_finished or self.loop is None:
            return None
        return asyncio.run_coroutine_threadsafe(self.cover_open(), self.loop).result(10)


NAMES = {"pick_up_tips": ("tip_spots",), "drop_tips": ("tip_spots",), "aspirate": ("resources",),
         "dispense": ("resources",), "move_plate": ("plate", "to")}


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
        return machine.cover_open_now() is True

    def set_cap(v):
        machine.volume_cap = float(v)

    signals = [
        Signal("connected", read=lambda: bool(machine.setup_finished), type="boolean"),
        Signal("connect_error", read=lambda: machine.error, type="string"),
        Signal("setup_finished", read=lambda: bool(machine.setup_finished), type="boolean"),
        Signal("cover_open", read=machine.cover_open_now, type="boolean"),
        Signal("cover_closed", read=lambda: machine.cover_open_now() is False, type="boolean"),
        Signal("robot_access_ready", read=access_ready, type="boolean"),
    ]
    settings = [Setting("volume_cap", write=set_cap, read=lambda: machine.volume_cap, unit="uL",
                        limits={"min": 0.5, "max": 1000})]
    return BoundDriver(device={}, signals=signals, settings=settings, actions=[make_action(n) for n in ACTIONS],
                       estop=lambda: loop.run(machine.stop(), timeout=30), setup=lambda: loop.run(machine.setup()),
                       extra={"pylabrobot": {"machine": "LiquidHandler", "backend": "STAR"}})


def Device():
    return build(Machine(Backend(load_config())))


def probe(cfg: dict) -> str:
    try:
        import pylabrobot                                        # noqa: F401
    except ImportError:
        raise DeviceFault("pylabrobot is not installed (pip install pylabrobot)") from None
    p = pathlib.Path(cfg.get("deck_file") or "")
    if not p.is_file():
        raise DeviceFault(f"deck layout file {p} not found; save one from PyLabRobot (lh.deck.save)")
    return f"pylabrobot importable; deck layout {p.name} found. The STAR is contacted on the first `mhp node` run"


Device.probe = probe                                             # noqa: E305  mhp node setup looks here
