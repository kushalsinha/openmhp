"""Simulated twin of the Vi-CELL BLU: a fake OPC UA server with the automation lock, a 3-minute count clock
(scaled by OPENMHP_SIM_TIME_SCALE), reagent uses that run down and plausible CHO viability results."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

N = real.DEFAULT_NODES
CELL_TYPES = {"CHO": (2.3e6, 0.93, 14.5), "HEK293": (1.8e6, 0.95, 15.5), "Hybridoma": (1.2e6, 0.90, 13.0),
              "Mammalian": (2.0e6, 0.92, 14.0)}
DURATION = {"count": 180, "prime": 240, "clean": 600}


class _Node:
    def __init__(self, server, nid): self.server, self.nid = server, nid
    def get_value(self): return self.server.read(self.nid)
    def set_value(self, v): self.server.values[self.nid] = v
    def call_method(self, mid, *args): return self.server.call(self.nid, mid, *args)


class FakeServer:
    def __init__(self, scale):
        self.scale, self.log, self.results = scale, [], {}
        self.values = {N["status"]: 1, N["lock_state"]: 2, N["reagent"]: 180, N["cell_types"]: list(CELL_TYPES),
                       N["sample_position"]: None, N["carousel_present"]: True}
        self.job, self.until = None, 0.0

    def get_node(self, nid): return _Node(self, nid)

    def _tick(self):
        if self.job and time.monotonic() >= self.until:
            kind, name, cfg = self.job
            self.job = None
            self.values[N["status"]] = 1
            if kind == "count":
                conc, viab, diam = CELL_TYPES.get(cfg["cell_type"], CELL_TYPES["Mammalian"])
                total = conc * random.gauss(1, 0.05) * cfg["dilution"]
                v = min(0.999, viab * random.gauss(1, 0.01))
                self.results[name] = {"CellCount": int(total / 1e4), "ViableCellCount": int(total * v / 1e4),
                                      "ViabilityPercent": round(100 * v, 1), "AverageDiameter": round(diam * random.gauss(1, 0.02), 2),
                                      "ViableCellsPerMl": round(total * v, -3), "TotalCellsPerMl": round(total, -3),
                                      "ImagePath": f"sim://images/{name}" if cfg["save_images"] else None}

    def read(self, nid):
        self._tick()
        if nid not in self.values:
            raise real.DeviceFault(f"BadNodeIdUnknown: {nid}")
        return self.values[nid]

    def call(self, obj, mid, *args):
        self._tick()
        self.log.append((mid.rsplit(".", 1)[-1], args))
        if mid == N["request_lock"]:
            self.values[N["lock_state"]] = 1; return 1
        if mid == N["release_lock"]:
            self.values[N["lock_state"]] = 2; return 1
        if self.values[N["lock_state"]] != 1 and mid in (N["start_sample"], N["prime"], N["clean"]):
            return 3                                             # NotLocked
        if mid == N["start_sample"]:
            if self.job:
                return 0
            name, row, col, dil, _tag, ctype, _qc, save, _wash = args
            self.values[N["reagent"]] -= 1
            self.values[N["status"]] = 4
            self.job = ("count", name, {"cell_type": ctype, "dilution": dil, "save_images": bool(save)})
            self.until = time.monotonic() + DURATION["count"] * self.scale
            return 1
        if mid in (N["prime"], N["clean"]):
            kind = "prime" if mid == N["prime"] else "clean"
            self.values[N["status"]] = 3
            self.job = (kind, None, {})
            self.until = time.monotonic() + DURATION[kind] * self.scale
            return 1
        if mid == N["stop"]:
            self.job = None; self.values[N["status"]] = 1; return 1
        if mid in (N["pause"], N["resume"], N["eject_stage"]):
            return 1
        if mid == N["get_results"]:
            r = self.results.get(args[4])
            return [r] if r else []
        raise real.DeviceFault(f"BadMethodInvalid: {mid}")


class SimBackend(real.ViCellBackend):
    def __init__(self, cfg, server):
        super().__init__(cfg)
        self.server = server

    def open(self):
        self.client = self.server


class SimViCellBlu(real.ViCellBlu):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"url": "opc.tcp://sim:4840", "allowed_cell_types": [], "max_minutes": 20}
        self.server = FakeServer(self.scale)

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.server)
