"""High-level meter reader: wake-up preamble, request TX, 2-stage RX.

Mirrors the upstream C ``get_meter_data`` / ``receive_radian_frame``
sequences from neutrinus/everblu-meters.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from . import cc1101_regs as R
from .cc1101 import CC1101, CC1101Error
from .config import Config
from .gpio import GPIO
from .radian import (
    MeterReading,
    decode_4bitpbit,
    make_master_request,
    parse_meter_report,
)

log = logging.getLogger(__name__)


class ReaderError(RuntimeError):
    pass


# Number of wake-up preamble blocks (each 8 bytes of 0x55). 77 blocks at
# 2.4 kbps ≈ 2.05 s, matching the C reference.
WUP_BLOCKS = 77
WUP_BLOCK = bytes([0x55] * 8)

# Expected ACK (~18 bytes) then index frame (~124 bytes) in raw (4x
# oversampled) form.
ACK_FRAME_BYTES = 0x12
INDEX_FRAME_BYTES = 0x7C


def in_listen_window(cfg: Config, now: Optional[datetime] = None) -> bool:
    """Return True if the meter is expected to be awake right now."""
    now = now or datetime.now()
    if now.weekday() not in cfg.meter.listen_weekdays:
        return False
    t = now.time()
    return cfg.meter.listen_start <= t <= cfg.meter.listen_end


class MeterReader:
    def __init__(self, cfg: Config, radio: Optional[CC1101] = None,
                 gpio: Optional[GPIO] = None) -> None:
        self.cfg = cfg
        self._owns_radio = radio is None
        self._owns_gpio = gpio is None
        self.radio = radio or CC1101(
            bus=cfg.radio.spi_bus,
            device=cfg.radio.spi_device,
            speed_hz=cfg.radio.spi_speed_hz,
        )
        self.gpio = gpio or GPIO(cfg.gpio.chip, (cfg.gpio.gdo0_pin, cfg.gpio.gdo2_pin))

    # ---------------------------------------------------------- lifecycle
    def close(self) -> None:
        if self._owns_radio:
            self.radio.close()
        if self._owns_gpio:
            self.gpio.close()

    def __enter__(self) -> "MeterReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------ configuration
    def configure(self) -> None:
        self.radio.reset()
        self.radio.apply_default_config()
        if self.cfg.radio.freq_offset_hz:
            target = self.cfg.radio.frequency_hz + self.cfg.radio.freq_offset_hz
            self.radio.set_frequency(target, self.cfg.radio.xtal_hz)
        self.radio.flush_rx()
        self.radio.flush_tx()

    # ---------------------------------------------------- wake-up + TX
    def _transmit_wake_and_request(self, request: bytes) -> None:
        """Send 2s of 0x55 wake-up bytes, then the request frame."""
        # Switch to raw mode: no preamble/sync, infinite packet length.
        self.radio.write_reg(R.MDMCFG2, 0x00)
        self.radio.write_reg(R.PKTCTRL0, 0x02)

        # Prime FIFO and enter TX.
        self.radio.flush_tx()
        self.radio.write_burst(R.TX_FIFO, WUP_BLOCK)
        self.radio.strobe(R.STX)
        time.sleep(0.010)  # allow TX calibration

        blocks_remaining = WUP_BLOCKS - 1
        request_sent = False
        deadline = time.monotonic() + 5.0  # absolute TX timeout

        while time.monotonic() < deadline:
            status = self.radio.strobe(R.SNOP)
            state = (status >> 4) & 0x07
            free = status & 0x0F
            if state != R.STATE_TX:
                # Fell out of TX (FIFO underflow or finished)
                break

            if blocks_remaining > 0:
                if free < 10:
                    time.sleep(0.020)  # ~1 block at 2.4 kbps
                    continue
                self.radio.write_burst(R.TX_FIFO, WUP_BLOCK)
                blocks_remaining -= 1
            elif not request_sent:
                # Give the FIFO time to drain so the 39-byte frame fits.
                time.sleep(0.130)
                self.radio.write_burst(R.TX_FIFO, request)
                request_sent = True
            else:
                time.sleep(0.010)

        # Flush any residue and restore modem settings.
        self.radio.flush_tx()
        self.radio.write_reg(R.MDMCFG2, 0x02)
        self.radio.write_reg(R.PKTCTRL0, 0x00)

    # ----------------------------------------------------- two-stage RX
    def _receive_radian_frame(self, expected_bytes: int,
                              timeout_s: float) -> bytes:
        """Capture a Radian frame. Two-stage: first find the 0x55 sync,
        then switch to the trailing 0xFF marker and pull data.
        """
        buf_size = expected_bytes * 4 + 32
        self.radio.flush_rx()
        self.radio.write_reg(R.MCSM1, 0x0F)    # CCA always; default to RX
        self.radio.write_reg(R.MDMCFG2, 0x02)  # 2-FSK, 16/16 sync
        self.radio.write_reg(R.SYNC1, 0x55)
        self.radio.write_reg(R.SYNC0, 0x50)
        self.radio.write_reg(R.MDMCFG4, 0xF6)  # 58 kHz BW
        self.radio.write_reg(R.MDMCFG3, 0x83)  # 2.4 kbps
        self.radio.write_reg(R.PKTLEN, 1)
        self.radio.enter_rx()

        pin = self.cfg.gpio.gdo0_pin
        stage_deadline = time.monotonic() + timeout_s
        remaining = lambda: max(0.0, stage_deadline - time.monotonic())

        if not self.gpio.wait_high(pin, remaining()):
            raise ReaderError("timeout waiting for first sync")

        # Drain the 1-byte sync capture.
        while self.gpio.read(pin):
            if self.radio.rx_bytes() > 0:
                self.radio.read_burst(R.RX_FIFO, self.radio.rx_bytes())
            if remaining() <= 0:
                raise ReaderError("timeout during stage-1 drain")
            time.sleep(0.002)

        # Stage 2: re-arm for the 0xFFF0 trailing sync at 9.59 kbps.
        self.radio.write_reg(R.SYNC1, 0xFF)
        self.radio.write_reg(R.SYNC0, 0xF0)
        self.radio.write_reg(R.MDMCFG4, 0xF8)  # 9.59 kbps
        self.radio.write_reg(R.MDMCFG3, 0x83)
        self.radio.write_reg(R.PKTCTRL0, 0x02)  # infinite length
        self.radio.flush_rx()
        self.radio.enter_rx()

        if not self.gpio.wait_high(pin, remaining()):
            raise ReaderError("timeout waiting for second sync")

        raw = bytearray()
        expected_raw = ((expected_bytes * 11) // 8 + 1) * 4
        while len(raw) < expected_raw and remaining() > 0:
            n = self.radio.rx_bytes()
            if n:
                raw.extend(self.radio.read_burst(R.RX_FIFO, n))
            else:
                time.sleep(0.002)
            if not self.gpio.read(pin) and not n:
                # End of packet and nothing left to drain.
                break

        self.radio.strobe(R.SIDLE)
        self.radio.flush_rx()

        # Restore defaults.
        self.radio.write_reg(R.MDMCFG4, 0xF6)
        self.radio.write_reg(R.MDMCFG3, 0x83)
        self.radio.write_reg(R.PKTCTRL0, 0x00)
        self.radio.write_reg(R.PKTLEN, 38)
        self.radio.write_reg(R.SYNC1, 0x55)
        self.radio.write_reg(R.SYNC0, 0x00)
        self.radio.write_reg(R.MCSM1, 0x00)
        return bytes(raw)

    # ---------------------------------------------------- public API
    def read(self) -> MeterReading:
        """Wake the meter, request the index, decode and parse the reply."""
        if not in_listen_window(self.cfg):
            log.warning(
                "Outside the meter's listen window (%s-%s Mon-Sat); "
                "the meter will likely not respond.",
                self.cfg.meter.listen_start, self.cfg.meter.listen_end,
            )

        self.configure()
        request = make_master_request(self.cfg.meter.year, self.cfg.meter.serial)
        log.debug("request frame: %s", request.hex())

        self._transmit_wake_and_request(request)

        # Sleep through inter-frame gap (~43 ms of noise + ~34 ms of 01
        # pattern before the ACK preamble).
        time.sleep(0.030)

        # First receive: ACK (~18 bytes). Errors here aren't fatal; the
        # meter still sends the index frame afterwards.
        try:
            self._receive_radian_frame(ACK_FRAME_BYTES, timeout_s=0.150)
        except ReaderError as exc:
            log.debug("ACK phase: %s", exc)

        time.sleep(0.030)

        raw = self._receive_radian_frame(INDEX_FRAME_BYTES, timeout_s=0.700)
        log.debug("raw index frame (%d bytes): %s", len(raw), raw.hex())

        decoded = decode_4bitpbit(raw)
        log.debug("decoded frame (%d bytes): %s", len(decoded), decoded.hex())

        return parse_meter_report(decoded)
