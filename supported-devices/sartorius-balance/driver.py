"""Sartorius SBI balance over serial.

SBI commands are the ESC control character (0x1B) followed by one letter or an `x<n>_` code. The
declarative serial driver refuses control characters in commands, so this subclass prefixes the bytes
in `serial.prefix` of descriptor.yaml (written as "\\x1b") to every command; everything else is declared.
"""
import re

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class Device(SerialAsciiDriver):
    def _encode(self, cmd: str) -> bytes:
        prefix = str(self.cfg.get("prefix", "")).encode().decode("unicode_escape")
        return prefix.encode() + super()._encode(cmd)

    @staticmethod
    def _text(raw) -> str:
        # the print frame puts spaces between the sign and the digits ("-   0.0012 g"): join them so
        # the sign is kept when the number is parsed
        return re.sub(r"([-+])\s+(?=\d)", r"\1", SerialAsciiDriver._text(raw))
