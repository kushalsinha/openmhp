"""MHP driver for LabJack T4 / T7 / T8 DAQs through the LJM library (labjack-ljm).

Every LJM call lives in LjmBackend so the simulated twin can replace it. Register names (AIN0, DAC0, FIO0,
DIO_STATE, AIN0_RANGE, SERIAL_NUMBER, ...) and calls (openS, eReadName(s), eWriteName(s), eStreamStart/Read/Stop,
listAll, getHandleInfo, close) are the ones LabJack's open examples use; see references/ljm.md.
"""
from __future__ import annotations

import csv
import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
AIN = ("AIN0", "AIN1", "AIN2", "AIN3")
FIO = ("FIO0", "FIO1", "FIO2", "FIO3")
DAC = ("DAC0", "DAC1")
STREAM_ABOVE_HZ = 100            # slower than this: paced eReadNames; faster: hardware-timed stream
DEVICE_TYPES = {4: "T4", 7: "T7", 8: "T8"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class LjmBackend:
    """labjack.ljm calls, nothing else."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.h = None
        self.info: dict = {}

    def open(self) -> None:
        from labjack import ljm
        self.ljm = ljm
        ident = str(self.cfg.get("identifier") or "ANY")
        self.h = ljm.openS("ANY", "ANY", ident)
        dt, ct, serial, ip, port, _ = ljm.getHandleInfo(self.h)
        self.info = {"device_type": DEVICE_TYPES.get(int(dt), f"type {dt}"), "serial_number": str(int(serial)),
                     "ip": ljm.numberToIP(ip) if ct == ljm.constants.ctTCP else None}

    def close(self) -> None:
        if self.h is not None:
            self.ljm.close(self.h)

    def read(self, name: str) -> float:
        return float(self.ljm.eReadName(self.h, name))

    def reads(self, names: list[str]) -> list[float]:
        return [float(v) for v in self.ljm.eReadNames(self.h, len(names), list(names))]

    def write(self, name: str, value: float) -> None:
        self.ljm.eWriteName(self.h, name, float(value))

    def writes(self, names: list[str], values: list[float]) -> None:
        self.ljm.eWriteNames(self.h, len(names), list(names), [float(v) for v in values])

    def stream_start(self, names: list[str], rate_hz: float, scans_per_read: int) -> float:
        addresses = self.ljm.namesToAddresses(len(names), list(names))[0]
        return float(self.ljm.eStreamStart(self.h, scans_per_read, len(names), addresses, rate_hz))

    def stream_read(self) -> list[float]:
        data, device_backlog, ljm_backlog = self.ljm.eStreamRead(self.h)
        return [float(v) for v in data]

    def stream_stop(self) -> None:
        self.ljm.eStreamStop(self.h)


class LabJackT(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.values = {"dac0": 0.0, "dac1": 0.0, "fio0": False, "fio1": False, "fio2": False, "fio3": False, "ain_range_0": 10}
        self.last_sample = None

    def make_backend(self):
        return LjmBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                       # noqa: BLE001  ImportError, ljm.LJMError
                raise DeviceFault(f"cannot open the LabJack ({self.cfg.get('identifier', 'ANY')}): {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _call(self, what: str, fn, *args):
        try:
            return fn(*args)
        except (DeviceFault, InvalidValue, JobCancelled):
            raise
        except Exception as e:                           # noqa: BLE001  LJMError is transient more often than not
            raise DeviceFault(f"{what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        hw = self._hw()
        if name in ("ain0", "ain1", "ain2", "ain3"):
            return round(self._call(name, hw.read, name.upper()), 6)
        if name == "dio_state":
            return int(self._call("DIO_STATE", hw.read, "DIO_STATE"))
        if name == "device_type":
            return hw.info["device_type"]
        if name == "serial_number":
            return hw.info["serial_number"]
        if name == "last_sample":
            return self.last_sample
        if name in self.values:
            return self.values[name]
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        hw = self._hw()
        if name in ("dac0", "dac1"):
            self._call(name.upper(), hw.write, name.upper(), float(value))
        elif name in ("fio0", "fio1", "fio2", "fio3"):
            self._call(name.upper(), hw.write, name.upper(), 1.0 if value else 0.0)
        elif name == "ain_range_0":
            if hw.info["device_type"] == "T4":
                raise InvalidValue("the T4's AIN0-AIN3 are fixed +/-10 V inputs; AIN0_RANGE is not settable")
            self._call("AIN0_RANGE", hw.write, "AIN0_RANGE", float(value))
        else:
            raise InvalidValue(f"unknown setting {name}")
        self.values[name] = value

    # ---- sampling ------------------------------------------------------------------------- #
    def on_invoke(self, job: Job):
        if job.action != "sample":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        channels, rate, seconds = list(p["channels"]), float(p["rate_hz"]), float(p["seconds"])
        total = max(1, int(round(rate * seconds)))
        scale = self.time_scale()
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        root.mkdir(parents=True, exist_ok=True)
        file = root / f"{time.strftime('%Y%m%d-%H%M%S')}_sample_{job.id}.csv"
        sums = [0.0] * len(channels)
        n = 0
        with file.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", *channels])
            if rate <= STREAM_ABOVE_HZ:
                t0 = time.monotonic()
                while n < total:
                    self.checkpoint(job, n / total, phase="sampling")
                    row = self._call("eReadNames", hw.reads, channels)
                    w.writerow([round(n / rate, 6), *(round(v, 6) for v in row)])
                    sums = [s + v for s, v in zip(sums, row)]
                    n += 1
                    due = t0 + n / rate * scale
                    while time.monotonic() < due:
                        time.sleep(min(0.01, due - time.monotonic()))
            else:
                per_read = max(1, int(rate / 2))
                actual = self._call("eStreamStart", hw.stream_start, channels, rate, per_read)
                try:
                    while n < total:
                        self.checkpoint(job, n / total, phase="streaming")
                        data = self._call("eStreamRead", hw.stream_read)
                        for k in range(0, len(data), len(channels)):
                            if n >= total:
                                break
                            row = data[k:k + len(channels)]
                            w.writerow([round(n / actual, 6), *(round(v, 6) for v in row)])
                            sums = [s + v for s, v in zip(sums, row)]
                            n += 1
                finally:
                    try:
                        hw.stream_stop()
                    except Exception:                    # noqa: BLE001  the stream is already stopped
                        pass
                rate = actual
        result = {"csv": str(file), "samples": n, "channels": channels, "rate_hz": round(rate, 3),
                  "duration_s": round(n / rate, 3), "mean_V": {c: round(s / n, 6) for c, s in zip(channels, sums)}}
        self.last_sample = result
        self.emit_signal("last_sample", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.writes(list(DAC) + list(FIO), [0.0] * (len(DAC) + len(FIO)))
        except Exception:                                # noqa: BLE001  must not raise
            pass
        for k in ("dac0", "dac1"):
            self.values[k] = 0.0
        for k in ("fio0", "fio1", "fio2", "fio3"):
            self.values[k] = False

    # ---- setup-time checks (`mhp node setup`) ------------------------------------------------ #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "devices":
            return []
        try:
            from labjack import ljm
        except ImportError:
            return []
        n, types, conns, serials, ips = ljm.listAll(ljm.constants.dtANY, ljm.constants.ctANY)
        out = []
        for i in range(n):
            note = DEVICE_TYPES.get(int(types[i]), f"type {types[i]}") + (" USB" if conns[i] == ljm.constants.ctUSB else f" {ljm.numberToIP(ips[i])}")
            out.append((str(int(serials[i])), note))
        return out or [("ANY", "no device found now; ANY opens the first one at run time")]

    @classmethod
    def probe(cls, cfg: dict) -> str:
        try:
            from labjack import ljm                      # noqa: F401
        except ImportError:
            raise DeviceFault("labjack-ljm is not installed (pip install labjack-ljm, plus the LJM library from labjack.com)") from None
        hw = LjmBackend(cfg)
        try:
            hw.open()
            serial, product = hw.reads(["SERIAL_NUMBER", "PRODUCT_ID"])
        except Exception as e:                           # noqa: BLE001
            raise DeviceFault(f"no LabJack answers for identifier {cfg.get('identifier', 'ANY')!r}: {type(e).__name__}: {e}") from None
        finally:
            hw.close()
        return f"{hw.info['device_type']} serial {int(serial)} (PRODUCT_ID {product:g}) answers"
