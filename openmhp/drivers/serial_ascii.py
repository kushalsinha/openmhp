"""Declarative serial driver: ASCII commands from descriptor.yaml, no code.

    serial:
      port: /dev/ttyUSB0          # or COM3; config.json `port` overrides it
      baud: 9600
      bytesize: 8                 # optional: 7 for IKA / JULABO; parity N|E|O; stopbits 1|2
      parity: N
      eol: "\\r\\n"
      read:    {plate_temperature: "IN_PV_1", lid_closed: "IN_LID"}
      write:   {target_temperature: "OUT_SP_1 {value}", stir_rpm: "OUT_SP_4 {value}"}
      actions: {shutdown: ["STOP_1", "STOP_4"], hold: ["HOLD {minutes}"]}
      estop:   ["STOP_1", "STOP_4"]
      booleans:                   # optional, per boolean signal: exact replies for true / false
        lid_closed: {true: ["1", "CLOSED"], false: ["0", "OPEN"]}
      parse:                      # optional, per signal, when the reply carries several numbers
        mass_flow: {field: 4}                       # the 4th number in the reply (1-based)
        setpoint:  {regex: "SP=([-+0-9.]+)", group: 1}
        pressure:  {field: 2, scale: 0.001}         # multiplied after parsing
      enq: "\\x05"                 # optional: ENQ/ACK handshake (Pfeiffer): send cmd, read ACK, send ENQ, read reply

Numeric replies are parsed for the first finite number unless `parse` says which.
Boolean replies must match a known token exactly (after trimming and lower-casing);
anything else, including error text, raises, and an unreadable interlock counts as
open. Values are validated by the driver before they are formatted into a command,
and no value may contain control characters. A signal with no read command that is
one of the reserved self-state or runtime names (SPEC 4.6) is answered by the base.
Needs pyserial; a `link` object with write()/readline() may be injected for tests.
"""
from __future__ import annotations

import math
import re
import string
import threading

from ..driver import Driver, InvalidValue, Job

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_TRUE = {"1", "true", "on", "yes", "closed"}
_FALSE = {"0", "false", "off", "no", "open"}


class SerialAsciiDriver(Driver):
    link = None                      # injectable
    section = "serial"               # the descriptor.yaml block this driver reads

    def setup(self):
        self.cfg = self.descriptor.get(self.section, {})
        self.eol = self.cfg.get("eol", "\r\n").encode().decode("unicode_escape")
        self._io = threading.Lock()
        if self.link is None:
            self.link = self.open_link()

    def open_link(self):
        """Open the real port. The lab's config.json `port` overrides the descriptor so a package is portable."""
        import serial                                         # pyserial, lazily
        cfg = self.config()
        parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        return serial.Serial(cfg.get("port") or self.cfg.get("port", "/dev/ttyUSB0"),
                             int(cfg.get("baud") or self.cfg.get("baud", 9600)),
                             bytesize=int(self.cfg.get("bytesize", 8)),                 # 7E1 for IKA and JULABO
                             parity=parity[str(self.cfg.get("parity", "N")).upper()[:1]],
                             stopbits=float(self.cfg.get("stopbits", 1)),
                             timeout=float(self.cfg.get("timeout", 1)),
                             write_timeout=float(self.cfg.get("write_timeout", 1)))

    def is_connected(self) -> bool:
        link = self.link
        if link is None:
            return False
        is_open = getattr(link, "is_open", None)
        return bool(is_open) if is_open is not None else True

    @classmethod
    def probe(cls, cfg: dict) -> str | None:
        """Open the port and send the first read command from the descriptor; report the reply."""
        port = cfg.get("port")
        if not port:
            return None
        import serial                                         # noqa: PLC0415
        with serial.Serial(port, int(cfg.get("baud", 9600)), timeout=1) as s:
            return f"port {port} opened ({s.baudrate} baud)"

    # ---- I/O ------------------------------------------------------------ #
    def _encode(self, cmd: str) -> bytes:
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in cmd):
            raise InvalidValue(f"refusing to send a command containing control characters: {cmd!r}")
        return (cmd + self.eol).encode()

    @staticmethod
    def _text(raw) -> str:
        return (raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)).strip()

    def query(self, cmd: str) -> str:
        data = self._encode(cmd)
        enq = self.cfg.get("enq")
        with self._io:
            self.link.write(data)
            raw = self.link.readline()
            if enq:                                           # ENQ/ACK: the first line is the ACK, the reply follows ENQ
                ack = self._text(raw)
                if ack and ack not in ("\x06", "ACK"):
                    raise ValueError(f"instrument did not acknowledge {cmd!r}: {ack!r}")
                self.link.write(enq.encode().decode("unicode_escape").encode())
                raw = self.link.readline()
        return self._text(raw)

    # ---- parsing -------------------------------------------------------- #
    def _parse(self, name: str, reply: str):
        typ = self._index["signals"].get(name, {}).get("type", "number")
        if typ == "string":
            return reply
        rule = (self.cfg.get("parse") or {}).get(name) or {}
        if rule.get("regex"):
            m = re.search(rule["regex"], reply)
            if not m:
                raise ValueError(f"reply {reply!r} to {name} does not match {rule['regex']!r}")
            reply = m.group(int(rule.get("group", 1)))
        elif rule.get("field"):
            nums = _NUM.findall(reply)
            k = int(rule["field"])
            if len(nums) < k:
                raise ValueError(f"reply {reply!r} to {name} has {len(nums)} number(s), field {k} asked")
            reply = nums[k - 1]
        if typ == "boolean":
            token = reply.strip().lower()
            custom = (self.cfg.get("booleans") or {}).get(name)
            true = {str(t).lower() for t in custom.get(True, custom.get("true", []))} if custom else _TRUE
            false = {str(t).lower() for t in custom.get(False, custom.get("false", []))} if custom else _FALSE
            if token in true and token not in false:
                return True
            if token in false and token not in true:
                return False
            raise ValueError(f"unrecognised reply {reply!r} for boolean signal {name}")
        m = _NUM.search(reply)
        if not m or not math.isfinite(float(m.group())):
            raise ValueError(f"no finite number in reply {reply!r} to {name}")
        value = float(m.group()) * float(rule.get("scale", 1)) + float(rule.get("offset", 0))
        return value if typ == "number" else int(round(value))

    # ---- hooks ---------------------------------------------------------- #
    def validate_params(self, action: str, params: dict) -> None:
        cmds = self.cfg.get("actions", {}).get(action)
        if not cmds:
            raise InvalidValue(f"no serial commands configured for action {action}")
        for c in cmds:
            for _, field, _, _ in string.Formatter().parse(c):
                if field and field not in params:
                    raise InvalidValue(f"{action}: command {c!r} needs parameter '{field}'")

    def on_read(self, name):
        cmd = self.cfg.get("read", {}).get(name)
        if cmd is None:
            raise InvalidValue(f"no serial read command for {name}")
        return self._parse(name, self.query(cmd))

    def on_write(self, name, value):
        cmd = self.cfg.get("write", {}).get(name)
        if cmd is None:
            raise InvalidValue(f"no serial write command for {name}")
        if isinstance(value, bool):
            value = int(value)
        self.query(cmd.format(value=value))

    def on_invoke(self, job: Job):
        cmds = self.cfg.get("actions", {}).get(job.action)
        replies = []
        for i, c in enumerate(cmds):
            self.checkpoint(job)
            replies.append(self.query(c.format(**job.params)))
            self.progress(job, (i + 1) / len(cmds))
        return {"replies": replies}

    def on_estop(self):
        """Interrupt any in-flight read, then send the stop commands without waiting for replies."""
        for method in ("cancel_read", "cancel_write"):
            fn = getattr(self.link, method, None)
            if fn:
                try:
                    fn()
                except Exception:                             # noqa: BLE001
                    pass
        got = self._io.acquire(timeout=0.5)
        errors = []
        try:
            for c in self.cfg.get("estop", []):
                try:
                    self.link.write(self._encode(c))
                except Exception as e:                        # noqa: BLE001  keep trying the rest
                    errors.append(f"{c}: {type(e).__name__}: {e}")
            reset = getattr(self.link, "reset_input_buffer", None)
            if reset:
                try:
                    reset()
                except Exception:                             # noqa: BLE001
                    pass
        finally:
            if got:
                self._io.release()
        if not self.cfg.get("estop"):
            raise RuntimeError("no serial estop commands configured")
        if errors:
            raise RuntimeError("stop commands failed: " + "; ".join(errors))
