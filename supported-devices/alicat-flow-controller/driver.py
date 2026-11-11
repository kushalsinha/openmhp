"""Alicat MC/MCR over serial: everything is declared in descriptor.yaml `serial:`.

One override. Every Alicat command starts with the device's one-letter unit id (default `A`), which the
lab sets per device; descriptor.yaml writes the commands for unit A and this driver swaps that first
letter for config.json `unit_id` before sending, so one package serves a bus of up to 26 units.
"""
from openmhp.drivers.serial_ascii import SerialAsciiDriver


class Device(SerialAsciiDriver):
    def _encode(self, cmd: str) -> bytes:
        unit = str(self.config().get("unit_id") or "A").strip()[:1].upper() or "A"
        if cmd[:1] == "A":
            cmd = unit + cmd[1:]
        return super()._encode(cmd)
