"""CC1101 SPI driver.

Thin wrapper over ``spidev`` exposing strobes, single/burst register R/W,
FIFO access and the small set of helpers the reader and diagnostics need.
"""
from __future__ import annotations

import time
from typing import Iterable, Sequence

from . import cc1101_regs as R


class CC1101Error(RuntimeError):
    pass


class CC1101:
    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        speed_hz: int = 1_000_000,
        spi=None,
    ) -> None:
        """Open the SPI device. ``spi`` may be injected for tests/dry-run."""
        self._last_status = 0
        if spi is not None:
            self._spi = spi
        else:
            try:
                import spidev  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise CC1101Error(
                    "spidev not installed; `pip install spidev` "
                    "or inject a mock via the spi= argument"
                ) from exc
            self._spi = spidev.SpiDev()
            self._spi.open(bus, device)
            self._spi.max_speed_hz = speed_hz
            self._spi.mode = 0

    # ------------------------------------------------------------------ SPI
    def _xfer(self, data: Sequence[int]) -> list[int]:
        out = self._spi.xfer2(list(data))
        # First returned byte is the chip status byte.
        self._last_status = out[0] if out else 0
        return out

    @property
    def last_status(self) -> int:
        return self._last_status

    @property
    def state(self) -> int:
        """State field (bits 6:4) of the most recent chip status byte."""
        return (self._last_status >> 4) & 0x07

    @property
    def fifo_bytes_available(self) -> int:
        """FIFO_BYTES_AVAILABLE field (bits 3:0) of the status byte."""
        return self._last_status & 0x0F

    # ------------------------------------------------------ register R/W
    def write_reg(self, reg: int, value: int) -> None:
        self._xfer([reg | R.WRITE_SINGLE, value & 0xFF])

    def read_reg(self, reg: int) -> int:
        # Per CC1101 errata, status registers should be read twice; we do
        # a single read here and let callers that care about status regs
        # use ``read_status``.
        out = self._xfer([reg | R.READ_SINGLE, 0])
        return out[1]

    def read_status(self, reg: int) -> int:
        """Read a status register (0x30..0x3D) using burst bit, twice."""
        # The burst bit is required to target the status-register map.
        addr = reg | R.READ_BURST
        prev = None
        for _ in range(4):
            out = self._xfer([addr, 0])
            val = out[1]
            if prev is not None and val == prev:
                return val
            prev = val
        return prev if prev is not None else 0

    def write_burst(self, reg: int, values: Iterable[int]) -> None:
        payload = [reg | R.WRITE_BURST] + [v & 0xFF for v in values]
        self._xfer(payload)

    def read_burst(self, reg: int, length: int) -> list[int]:
        out = self._xfer([reg | R.READ_BURST] + [0] * length)
        return out[1:]

    def strobe(self, cmd: int) -> int:
        """Issue a command strobe and return the status byte."""
        self._xfer([cmd & 0xFF])
        return self._last_status

    # ----------------------------------------------------------- helpers
    def reset(self) -> None:
        self.strobe(R.SRES)
        time.sleep(0.001)

    def partnum(self) -> int:
        return self.read_status(R.PARTNUM)

    def version(self) -> int:
        return self.read_status(R.VERSION)

    def marcstate(self) -> int:
        return self.read_status(R.MARCSTATE) & 0x1F

    def rssi_dbm(self) -> float:
        return R.rssi_to_dbm(self.read_status(R.RSSI))

    def lqi(self) -> int:
        return self.read_status(R.LQI) & 0x7F

    def rx_bytes(self) -> int:
        """Number of bytes currently in the RX FIFO (masked)."""
        raw = self.read_status(R.RXBYTES)
        if raw & R.RXBYTES_OVERFLOW:
            # Overflow: caller should flush.
            pass
        return raw & R.RXBYTES_MASK

    def rx_overflow(self) -> bool:
        return bool(self.read_status(R.RXBYTES) & R.RXBYTES_OVERFLOW)

    def pktstatus(self) -> int:
        return self.read_status(R.PKTSTATUS)

    # --------------------------------------------------- configuration
    def apply_default_config(self) -> None:
        for reg, val in R.DEFAULT_CONFIG:
            self.write_reg(reg, val)
        self.write_burst(R.PATABLE, R.DEFAULT_PATABLE)

    def set_frequency(self, freq_hz: int, xtal_hz: int = 26_000_000) -> None:
        f2, f1, f0 = R.freq_to_regs(freq_hz, xtal_hz)
        self.write_reg(R.FREQ2, f2)
        self.write_reg(R.FREQ1, f1)
        self.write_reg(R.FREQ0, f0)

    def get_frequency(self, xtal_hz: int = 26_000_000) -> float:
        f2 = self.read_reg(R.FREQ2)
        f1 = self.read_reg(R.FREQ1)
        f0 = self.read_reg(R.FREQ0)
        return R.regs_to_freq(f2, f1, f0, xtal_hz)

    def dump_config(self) -> list[int]:
        """Return all 0x2F configuration registers as a list."""
        return self.read_burst(0x00, R.CFG_REGISTER_COUNT)

    def dump_patable(self) -> list[int]:
        return self.read_burst(R.PATABLE, 8)

    # ------------------------------------------------------ mode helpers
    def idle(self) -> None:
        self.strobe(R.SIDLE)
        while self.marcstate() != R.MARC_IDLE:
            time.sleep(0.0005)

    def flush_rx(self) -> None:
        self.strobe(R.SFRX)

    def flush_tx(self) -> None:
        self.strobe(R.SFTX)

    def enter_rx(self) -> None:
        self.strobe(R.SIDLE)
        self.strobe(R.SRX)
        # Wait until MARCSTATE reports RX (0x0D) or RX variants 0x0E/0x0F.
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            m = self.marcstate()
            if m in (0x0D, 0x0E, 0x0F):
                return
        raise CC1101Error(f"Failed to enter RX mode; MARCSTATE=0x{self.marcstate():02X}")

    def close(self) -> None:
        try:
            self._spi.close()
        except Exception:
            pass

    def __enter__(self) -> "CC1101":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
