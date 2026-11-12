"""Declarative SCPI driver: commands from descriptor.yaml, the instrument reached through VISA,
a raw TCP socket or a serial port. No code in the package.

    scpi:
      resource: "TCPIP0::192.168.1.20::inst0::INSTR"   # VISA; or "tcp://host:5025"; or "/dev/ttyUSB0" / "COM4"
      eol: "\\n"
      idn_match: "KEITHLEY"       # optional: *IDN? must contain this, else probe() refuses
      read:    {voltage: "MEAS:VOLT?", output_on: "OUTP?"}
      write:   {voltage_setpoint: "SOUR:VOLT {value}", output_on: "OUTP {value}"}
      actions: {reset: ["*RST", "*CLS"], sweep: ["SOUR:VOLT:START {start}", "INIT"]}
      estop:   ["OUTP OFF", "ABOR"]
      booleans: {output_on: {true: ["1", "ON"], false: ["0", "OFF"]}}
      parse:   {current: {field: 2}}

Same grammar as `serial_ascii` (parse rules, booleans, enq), so a package author learns one
shape. `resource` in the lab's config.json overrides the descriptor. `discover("resource")`
lists what pyvisa sees; `probe(cfg)` opens the resource and reads *IDN?. pyvisa is imported
lazily; a `link` object with write()/readline() may be injected for a twin.
"""
from __future__ import annotations

import re
import socket

from .serial_ascii import SerialAsciiDriver


class _VisaLink:
    """pyvisa resource behind the write()/readline() shape the base driver uses."""

    def __init__(self, inst, eol: str):
        self.inst, self.eol = inst, eol
        inst.write_termination = eol
        inst.read_termination = eol
        self.is_open = True

    def write(self, data: bytes) -> None:
        self.inst.write_raw(data)

    def readline(self) -> bytes:
        return self.inst.read_raw()

    def close(self) -> None:
        self.is_open = False
        self.inst.close()


class _SocketLink:
    """Raw SCPI over TCP (port 5025 on most LXI instruments)."""

    def __init__(self, host: str, port: int, timeout: float):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self.is_open = True

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def readline(self) -> bytes:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line

    def close(self) -> None:
        self.is_open = False
        self.sock.close()


def open_resource(resource: str, eol: str = "\n", timeout: float = 2.0):
    """Open a VISA string, tcp://host:port, or a serial device path."""
    if resource.startswith("tcp://"):
        host, _, port = resource[6:].partition(":")
        return _SocketLink(host, int(port or 5025), timeout)
    if "::" in resource:
        import pyvisa                                            # noqa: PLC0415  lazily
        rm = pyvisa.ResourceManager()
        inst = rm.open_resource(resource)
        inst.timeout = int(timeout * 1000)
        return _VisaLink(inst, eol)
    import serial                                                # noqa: PLC0415
    return serial.Serial(resource, 9600, timeout=timeout, write_timeout=timeout)


class ScpiVisaDriver(SerialAsciiDriver):
    section = "scpi"

    def open_link(self):
        cfg = self.config()
        resource = cfg.get("resource") or self.cfg.get("resource")
        if not resource:
            raise RuntimeError("no VISA resource: set `resource` in config.json (see config.example.json)")
        return open_resource(resource, self.eol, float(self.cfg.get("timeout", 2)))

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what not in ("resource", "resources"):
            return []
        try:
            import pyvisa                                        # noqa: PLC0415
            return sorted(pyvisa.ResourceManager().list_resources())
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError(f"pyvisa could not list resources ({type(e).__name__}: {e}); "
                               f"type the VISA string or tcp://host:5025 instead") from None

    @classmethod
    def probe(cls, cfg: dict) -> str | None:
        resource = cfg.get("resource")
        if not resource:
            return None
        link = open_resource(resource)
        try:
            link.write(b"*IDN?\n")
            idn = link.readline()
            idn = (idn.decode(errors="replace") if isinstance(idn, bytes) else str(idn)).strip()
        finally:
            close = getattr(link, "close", None)
            if close:
                close()
        if not idn:
            raise RuntimeError(f"{resource} answered nothing to *IDN?")
        want = cfg.get("idn_match")
        if want and not re.search(re.escape(str(want)), idn, re.I):
            raise RuntimeError(f"{resource} is {idn!r}, not a {want} instrument")
        return f"{resource}: {idn}"
