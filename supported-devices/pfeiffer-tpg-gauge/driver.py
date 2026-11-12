"""Pfeiffer TPG 36x/26x over serial: everything is declared in descriptor.yaml `serial:` (mnemonic + ENQ/ACK).

One override. `SEN,a,b` encodes a gauge switch as 0 = no change, 1 = off, 2 = on, while the generic
driver formats a boolean as 1/0. The boolean is mapped True -> 2 and False -> 1 before formatting,
so `sensor_1_on: false` sends `SEN,1,0` (off) and never `SEN,0,0` (no change).
"""
from openmhp.drivers.serial_ascii import SerialAsciiDriver


class Device(SerialAsciiDriver):
    def on_write(self, name, value):
        if isinstance(value, bool):
            value = 2 if value else 1
        super().on_write(name, value)
