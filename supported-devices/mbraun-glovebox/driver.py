"""MBRAUN glovebox PLC over Modbus TCP: the declarative driver plus the three signals its grammar cannot
express. The antechamber and purge state codes are mapped to the names the glovebox class uses, and
`antechamber_idle` and `robot_access_ready` are derived from them and the door bits. Every register
is a placeholder (template package); the mapping lives here so the names stay once the map is fixed."""
from __future__ import annotations

from openmhp.drivers.modbus import ModbusDriver

ANTECHAMBER = {0: "idle", 1: "evacuating", 2: "refilling", 3: "at_box_pressure", 4: "fault"}
PURGE = {0: "off", 1: "purging", 2: "regenerating"}


class Device(ModbusDriver):
    def _code(self, name: str) -> int:
        return int(round(self._read_reg(self._spec("read", name))))

    def on_read(self, name):
        if name == "antechamber_state":
            code = self._code(name)
            return ANTECHAMBER.get(code, f"unknown_{code}")
        if name == "purge_state":
            code = self._code(name)
            return PURGE.get(code, f"unknown_{code}")
        if name == "antechamber_idle":
            return self._code("antechamber_state") == 0 and not bool(self._read_reg(self._spec("read", "antechamber_cycle_active")))
        if name == "robot_access_ready":
            inner_closed = bool(self._read_reg(self._spec("read", "inner_door_closed")))
            return (not inner_closed) and self.on_read("antechamber_idle")
        return super().on_read(name)
