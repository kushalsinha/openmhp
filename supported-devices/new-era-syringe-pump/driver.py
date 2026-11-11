"""New Era NE-1000 series pump over RS-232 (Basic mode).

Two things the declarative serial driver cannot express: every command carries the pump's two-digit
network address from config.json (`address`, 0-99), and infuse/withdraw must wait for the pump to stop
before they are done, which means polling DIS. Both live here; the command map stays in descriptor.yaml.
"""
import re
import time

from openmhp.driver import InvalidValue
from openmhp.drivers.serial_ascii import SerialAsciiDriver

_STATUS = re.compile(r"\x02?\d\d([A-Z?])")          # <STX> nn X ...: X is the pump's status letter


class Device(SerialAsciiDriver):
    def _encode(self, cmd: str) -> bytes:
        return super()._encode(f"{int(self.config().get('address', 0)):02d}{cmd}")

    def on_invoke(self, job):
        cmds = self.cfg.get("actions", {}).get(job.action) or []
        replies = []
        for i, c in enumerate(cmds):
            self.checkpoint(job)
            replies.append(self.query(c.format(**job.params)))
            if "?" in replies[-1]:                     # ?, ?NA, ?OOR, ?COM, ?IGN: refused, and RUN is last, so nothing moved
                raise InvalidValue(f"{job.action}: pump refused {c.format(**job.params)!r}: {replies[-1]!r}")
            self.progress(job, (i + 1) / (len(cmds) + 1))
        if cmds and cmds[-1] == "RUN":
            while True:
                self.checkpoint(job)
                replies.append(self.query("DIS"))
                m = _STATUS.match(replies[-1])
                if not m or m.group(1) not in ("I", "W"):
                    break
                time.sleep(0.2)
        return {"replies": replies}
