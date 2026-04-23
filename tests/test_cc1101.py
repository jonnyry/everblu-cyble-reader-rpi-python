"""Tests for CC1101 driver using a mocked SPI bus."""
from __future__ import annotations

from everblu import cc1101_regs as R
from everblu.cc1101 import CC1101


class FakeSpi:
    """In-memory model of the CC1101 register map & FIFO for tests."""

    def __init__(self) -> None:
        self.config_regs = [0] * 0x40
        self.status_regs = {
            R.PARTNUM: 0x00,
            R.VERSION: 0x14,
            R.MARCSTATE: 0x01,
            R.RSSI: 0x80,  # -74 dBm
            R.LQI: 0x00,
            R.RXBYTES: 0,
            R.TXBYTES: 0,
        }
        self.patable = [0] * 8
        self.tx_fifo: list[int] = []
        self.rx_fifo: list[int] = []
        self.log: list[tuple[int, list[int]]] = []
        self.state = R.STATE_IDLE

    @property
    def max_speed_hz(self):
        return 1_000_000

    @max_speed_hz.setter
    def max_speed_hz(self, v):
        pass

    @property
    def mode(self):
        return 0

    @mode.setter
    def mode(self, v):
        pass

    def open(self, bus, dev):
        pass

    def close(self):
        pass

    def _status_byte(self) -> int:
        return (self.state & 0x07) << 4

    def xfer2(self, data):
        header = data[0]
        payload = data[1:]
        self.log.append((header, list(payload)))
        reply = [self._status_byte()]
        addr = header & 0x3F
        burst = bool(header & 0x40)
        read = bool(header & 0x80)

        # Strobe (no payload).
        if 0x30 <= header <= 0x3D and not burst:
            # Command strobe semantics.
            if header == R.SRES:
                self.state = R.STATE_IDLE
            elif header == R.SIDLE:
                self.state = R.STATE_IDLE
                self.status_regs[R.MARCSTATE] = 0x01
            elif header == R.SRX:
                self.state = R.STATE_RX
                self.status_regs[R.MARCSTATE] = 0x0D
            elif header == R.STX:
                self.state = R.STATE_TX
                self.status_regs[R.MARCSTATE] = 0x13
            elif header == R.SFRX:
                self.rx_fifo.clear()
            elif header == R.SFTX:
                self.tx_fifo.clear()
            return reply  # 1-byte status response for strobes

        if read and burst:
            # Status registers live at 0x30..0x3D (read-burst only);
            # PATABLE/TX-FIFO/RX-FIFO at 0x3E/0x3F.
            if addr == R.PATABLE:
                for _ in payload:
                    reply.append(self.patable[(len(reply) - 1) % 8])
            elif addr == 0x3F:
                # RX_FIFO burst
                for _ in payload:
                    if self.rx_fifo:
                        reply.append(self.rx_fifo.pop(0))
                    else:
                        reply.append(0)
            elif addr in self.status_regs:
                for _ in payload:
                    reply.append(self.status_regs[addr])
            else:
                # General burst read of config regs
                for i, _ in enumerate(payload):
                    reply.append(self.config_regs[(addr + i) & 0x3F])
            return reply

        if read and not burst:
            if addr in self.status_regs and addr >= 0x30:
                for _ in payload:
                    reply.append(self.status_regs[addr])
            else:
                reply.append(self.config_regs[addr])
            return reply

        if not read and burst:
            if addr == R.PATABLE:
                for i, v in enumerate(payload):
                    self.patable[i & 7] = v & 0xFF
            elif addr == R.TX_FIFO:
                self.tx_fifo.extend(v & 0xFF for v in payload)
            else:
                for i, v in enumerate(payload):
                    self.config_regs[(addr + i) & 0x3F] = v & 0xFF
            return reply + list(payload)

        # single write
        self.config_regs[addr] = payload[0] & 0xFF
        return reply + list(payload)


def test_partnum_version():
    fake = FakeSpi()
    dev = CC1101(spi=fake)
    assert dev.partnum() == 0x00
    assert dev.version() == 0x14


def test_write_and_read_register():
    fake = FakeSpi()
    dev = CC1101(spi=fake)
    dev.write_reg(R.FREQ2, 0x10)
    dev.write_reg(R.FREQ1, 0xAF)
    dev.write_reg(R.FREQ0, 0x75)
    assert dev.read_reg(R.FREQ2) == 0x10
    assert dev.read_reg(R.FREQ1) == 0xAF
    assert dev.read_reg(R.FREQ0) == 0x75


def test_apply_default_config_matches_table():
    fake = FakeSpi()
    dev = CC1101(spi=fake)
    dev.apply_default_config()
    for reg, val in R.DEFAULT_CONFIG:
        assert fake.config_regs[reg] == val, f"reg 0x{reg:02X}"
    assert fake.patable == list(R.DEFAULT_PATABLE)


def test_frequency_roundtrip():
    fake = FakeSpi()
    dev = CC1101(spi=fake)
    dev.set_frequency(433_820_000)
    got = dev.get_frequency()
    assert abs(got - 433_820_000) < 500


def test_strobe_state_changes():
    fake = FakeSpi()
    dev = CC1101(spi=fake)
    dev.strobe(R.SIDLE)
    assert dev.marcstate() == 0x01
    dev.strobe(R.SRX)
    assert dev.marcstate() == 0x0D
