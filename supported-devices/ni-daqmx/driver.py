"""MHP driver for National Instruments DAQs (USB-6001/6008/6009, USB-621x, 63xx) through the nidaqmx Python package.

Every nidaqmx call lives in DaqmxBackend so the simulated twin can replace it. The calls (Task, add_ai_voltage_chan,
add_ao_voltage_chan, add_do_chan, cfg_samp_clk_timing, read, write, System.local().devices) are the ones in NI's
open nidaqmx-python examples; see references/nidaqmx.md. The NI-DAQmx runtime exists for Windows and Linux only.
"""
from __future__ import annotations

import csv
import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
AI = ("ai0", "ai1", "ai2", "ai3")
AO = ("ao0", "ao1")
LINES = ("port0_line0", "port0_line1", "port0_line2", "port0_line3")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class DaqmxBackend:
    """nidaqmx calls, nothing else. One short-lived Task per operation, as the NI examples do."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.dev = None
        self.product_type = ""
        self.task = None

    def open(self) -> None:
        if not self.cfg.get("device"):
            raise DeviceFault("config.json is missing or has no device name (copy config.example.json and fill it in)")
        import nidaqmx
        from nidaqmx.constants import AcquisitionType, LineGrouping
        self.nidaqmx, self.AcquisitionType, self.LineGrouping = nidaqmx, AcquisitionType, LineGrouping
        self.dev = str(self.cfg["device"])
        devices = {d.name: d for d in nidaqmx.system.System.local().devices}
        if self.dev not in devices:
            raise DeviceFault(f"NI-DAQmx knows no device {self.dev!r}; it knows {sorted(devices)} (check NI MAX)")
        self.product_type = str(devices[self.dev].product_type)

    def close(self) -> None:
        self.stream_stop()

    def read_ai(self, channels: list[str]) -> list[float]:
        with self.nidaqmx.Task() as task:
            for ch in channels:
                task.ai_channels.add_ai_voltage_chan(f"{self.dev}/{ch}")
            data = task.read()
        return [float(v) for v in (data if isinstance(data, list) else [data])]

    def write_ao(self, channel: str, volts: float) -> None:
        with self.nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(f"{self.dev}/{channel}")
            task.write(float(volts), auto_start=True)

    def write_do(self, line: str, high: bool) -> None:
        with self.nidaqmx.Task() as task:
            task.do_channels.add_do_chan(f"{self.dev}/{line.replace('_', '/')}", line_grouping=self.LineGrouping.CHAN_PER_LINE)
            task.write(bool(high), auto_start=True)

    def stream_start(self, channels: list[str], rate_hz: float, samples_per_read: int) -> float:
        task = self.nidaqmx.Task()
        for ch in channels:
            task.ai_channels.add_ai_voltage_chan(f"{self.dev}/{ch}")
        task.timing.cfg_samp_clk_timing(rate_hz, sample_mode=self.AcquisitionType.CONTINUOUS, samps_per_chan=samples_per_read * 4)
        task.start()
        self.task, self.n_ch = task, len(channels)
        return float(task.timing.samp_clk_rate)                                              # unverified attribute

    def stream_read(self, samples_per_read: int) -> list[list[float]]:
        """Rows of one value per channel."""
        data = self.task.read(number_of_samples_per_channel=samples_per_read, timeout=10.0)
        if self.n_ch == 1:
            return [[float(v)] for v in data]
        return [[float(data[c][k]) for c in range(self.n_ch)] for k in range(len(data[0]))]

    def stream_stop(self) -> None:
        if self.task is not None:
            try:
                self.task.stop()
            finally:
                self.task.close()
                self.task = None


class NIDaqmx(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.values = {"ao0": 0.0, "ao1": 0.0, **{line: False for line in LINES}}
        self.last_sample = None

    def make_backend(self):
        return DaqmxBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                       # noqa: BLE001  ImportError, DaqError
                raise DeviceFault(f"cannot open {self.cfg.get('device', '?')} through NI-DAQmx: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _call(self, what: str, fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except (DeviceFault, InvalidValue, JobCancelled):
            raise
        except Exception as e:                           # noqa: BLE001  nidaqmx.errors.DaqError
            raise DeviceFault(f"{what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        hw = self._hw()
        if name in AI:
            return round(self._call(name, hw.read_ai, [name])[0], 6)
        if name == "device":
            return hw.dev
        if name == "product_type":
            return hw.product_type
        if name == "port0_state":
            return sum(int(self.values[line]) << k for k, line in enumerate(LINES))
        if name == "last_sample":
            return self.last_sample
        if name in self.values:
            return self.values[name]
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        hw = self._hw()
        if name in AO:
            self._call(name, hw.write_ao, name, float(value))
        elif name in LINES:
            self._call(name, hw.write_do, name, bool(value))
        else:
            raise InvalidValue(f"unknown setting {name}")
        self.values[name] = value
        if name in LINES:
            self.emit_signal("port0_state", self.on_read("port0_state"))

    # ---- sampling ------------------------------------------------------------------------- #
    def on_invoke(self, job: Job):
        if job.action != "sample":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        channels, rate, seconds = list(p["channels"]), float(p["rate_hz"]), float(p["seconds"])
        total = max(1, int(round(rate * seconds)))
        per_read = max(1, min(total, int(rate / 2)))
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        root.mkdir(parents=True, exist_ok=True)
        file = root / f"{time.strftime('%Y%m%d-%H%M%S')}_sample_{job.id}.csv"
        sums, n = [0.0] * len(channels), 0
        actual = self._call("cfg_samp_clk_timing/start", hw.stream_start, channels, rate, per_read)
        try:
            with file.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_s", *channels])
                while n < total:
                    self.checkpoint(job, n / total, phase="sampling")
                    rows = self._call("read", hw.stream_read, min(per_read, total - n))
                    for row in rows:
                        w.writerow([round(n / actual, 6), *(round(v, 6) for v in row)])
                        sums = [s + v for s, v in zip(sums, row)]
                        n += 1
        finally:
            try:
                hw.stream_stop()
            except Exception:                            # noqa: BLE001  the task is already gone
                pass
        result = {"csv": str(file), "samples": n, "channels": channels, "rate_hz": round(actual, 3),
                  "duration_s": round(n / actual, 3), "mean_V": {c: round(s / n, 6) for c, s in zip(channels, sums)}}
        self.last_sample = result
        self.emit_signal("last_sample", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stream_stop()
                for ch in AO:
                    self.hw.write_ao(ch, 0.0)
                for line in LINES:
                    self.hw.write_do(line, False)
        except Exception:                                # noqa: BLE001  must not raise
            pass
        for ch in AO:
            self.values[ch] = 0.0
        for line in LINES:
            self.values[line] = False

    # ---- setup-time checks (`mhp node setup`) ------------------------------------------------ #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "devices":
            return []
        try:
            import nidaqmx
        except ImportError:
            return []
        return [(str(d.name), str(d.product_type)) for d in nidaqmx.system.System.local().devices]

    @classmethod
    def probe(cls, cfg: dict) -> str:
        try:
            import nidaqmx                               # noqa: F401
        except ImportError:
            raise DeviceFault("nidaqmx is not installed (pip install nidaqmx, plus the NI-DAQmx runtime from ni.com; Windows or Linux)") from None
        hw = DaqmxBackend(cfg)
        hw.open()
        v = hw.read_ai(["ai0"])[0]
        return f"{hw.dev} is a {hw.product_type}; ai0 reads {v:.4f} V"
