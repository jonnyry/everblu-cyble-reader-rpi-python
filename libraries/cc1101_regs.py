"""CC1101 register, strobe and status constants.

Addresses and values taken from the CC1101 datasheet (TI SWRS061) and from
the neutrinus/everblu-meters C reference implementation.
"""
from __future__ import annotations

# SPI access header bits
WRITE_SINGLE = 0x00
WRITE_BURST = 0x40
READ_SINGLE = 0x80
READ_BURST = 0xC0

# --- Configuration registers (0x00..0x2E) ---
IOCFG2 = 0x00
IOCFG1 = 0x01
IOCFG0 = 0x02
FIFOTHR = 0x03
SYNC1 = 0x04
SYNC0 = 0x05
PKTLEN = 0x06
PKTCTRL1 = 0x07
PKTCTRL0 = 0x08
ADDR = 0x09
CHANNR = 0x0A
FSCTRL1 = 0x0B
FSCTRL0 = 0x0C
FREQ2 = 0x0D
FREQ1 = 0x0E
FREQ0 = 0x0F
MDMCFG4 = 0x10
MDMCFG3 = 0x11
MDMCFG2 = 0x12
MDMCFG1 = 0x13
MDMCFG0 = 0x14
DEVIATN = 0x15
MCSM2 = 0x16
MCSM1 = 0x17
MCSM0 = 0x18
FOCCFG = 0x19
BSCFG = 0x1A
AGCCTRL2 = 0x1B
AGCCTRL1 = 0x1C
AGCCTRL0 = 0x1D
WOREVT1 = 0x1E
WOREVT0 = 0x1F
WORCTRL = 0x20
FREND1 = 0x21
FREND0 = 0x22
FSCAL3 = 0x23
FSCAL2 = 0x24
FSCAL1 = 0x25
FSCAL0 = 0x26
RCCTRL1 = 0x27
RCCTRL0 = 0x28
FSTEST = 0x29
PTEST = 0x2A
AGCTEST = 0x2B
TEST2 = 0x2C
TEST1 = 0x2D
TEST0 = 0x2E

CFG_REGISTER_COUNT = 0x2F  # 47 registers

# --- Command strobes (0x30..0x3D) ---
SRES = 0x30   # Reset chip
SFSTXON = 0x31
SXOFF = 0x32
SCAL = 0x33
SRX = 0x34
STX = 0x35
SIDLE = 0x36
SAFC = 0x37
SWOR = 0x38
SPWD = 0x39
SFRX = 0x3A
SFTX = 0x3B
SWORRST = 0x3C
SNOP = 0x3D

# --- FIFO / PATABLE ---
PATABLE = 0x3E
TX_FIFO = 0x3F
RX_FIFO = 0x3F  # read via READ_BURST|RX_FIFO == 0xFF, or READ_SINGLE|0x3F

# --- Status registers (read-only, burst bit must be set) ---
# Use these addresses directly with READ_BURST header.
PARTNUM = 0x30
VERSION = 0x31
FREQEST = 0x32
LQI = 0x33
RSSI = 0x34
MARCSTATE = 0x35
WORTIME1 = 0x36
WORTIME0 = 0x37
PKTSTATUS = 0x38
VCO_VC_DAC = 0x39
TXBYTES = 0x3A
RXBYTES = 0x3B
RCCTRL1_STATUS = 0x3C
RCCTRL0_STATUS = 0x3D

RXBYTES_MASK = 0x7F
RXBYTES_OVERFLOW = 0x80

# --- MARCSTATE values (subset) ---
MARC_SLEEP = 0x00
MARC_IDLE = 0x01
MARC_RX = 0x0D
MARC_TX = 0x13

# --- Chip status byte (returned on every SPI transfer) state field ---
STATE_IDLE = 0x00
STATE_RX = 0x01
STATE_TX = 0x02
STATE_FSTXON = 0x03
STATE_CALIBRATE = 0x04
STATE_SETTLING = 0x05
STATE_RX_OVERFLOW = 0x06
STATE_TX_UNDERFLOW = 0x07


# Default register configuration for the Radian/EverBlu protocol, ported
# verbatim from neutrinus/everblu-meters cc1101.c :: cc1101_configureRF_0().
# Each tuple is (register, value).
DEFAULT_CONFIG: tuple[tuple[int, int], ...] = (
    (IOCFG2, 0x0D),   # GDO2 = Serial Data Output (async)
    (IOCFG0, 0x06),   # GDO0 = assert on sync word, deassert at end of packet
    (FIFOTHR, 0x47),  # ADC retention, TX/RX FIFO threshold
    (SYNC1, 0x55),
    (SYNC0, 0x00),
    (PKTCTRL1, 0x00),  # no address check, no status append
    (PKTCTRL0, 0x00),  # fixed length, no CRC
    (FSCTRL1, 0x08),
    # Base frequency 433.82 MHz (FREQ = 0x10AF75 / 2^16 * 26 MHz)
    (FREQ2, 0x10),
    (FREQ1, 0xAF),
    (FREQ0, 0x75),
    (MDMCFG4, 0xF6),  # RX BW = 58 kHz
    (MDMCFG3, 0x83),  # 2.4 kbps
    (MDMCFG2, 0x02),  # 2-FSK, no Manchester, 16/16 sync
    (MDMCFG1, 0x00),
    (MDMCFG0, 0x00),
    (DEVIATN, 0x15),  # ~5.16 kHz deviation
    (MCSM1, 0x00),    # default to IDLE after RX/TX, CCA always
    (MCSM0, 0x18),
    (FOCCFG, 0x1D),
    (BSCFG, 0x1C),
    (AGCCTRL2, 0xC7),
    (AGCCTRL1, 0x00),
    (AGCCTRL0, 0xB2),
    (WORCTRL, 0xFB),
    (FREND1, 0xB6),
    (FSCAL3, 0xE9),
    (FSCAL2, 0x2A),
    (FSCAL1, 0x00),
    (FSCAL0, 0x1F),
    (TEST2, 0x81),
    (TEST1, 0x35),
    (TEST0, 0x09),
)

# PATABLE: index 0 is used when PA ramping disabled (our default).
# 0x60 ~= 0 dBm at 433 MHz per the datasheet.
DEFAULT_PATABLE: tuple[int, ...] = (0x60, 0, 0, 0, 0, 0, 0, 0)


def rssi_to_dbm(raw: int) -> float:
    """Convert the raw RSSI register value to dBm (datasheet formula)."""
    rssi_offset = 74
    if raw >= 128:
        return ((raw - 256) / 2.0) - rssi_offset
    return (raw / 2.0) - rssi_offset


def freq_to_regs(freq_hz: int, xtal_hz: int = 26_000_000) -> tuple[int, int, int]:
    """Compute FREQ2/FREQ1/FREQ0 register values for a target frequency."""
    word = round(freq_hz * (1 << 16) / xtal_hz)
    word &= 0xFFFFFF
    return (word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF


def regs_to_freq(freq2: int, freq1: int, freq0: int, xtal_hz: int = 26_000_000) -> float:
    word = (freq2 << 16) | (freq1 << 8) | freq0
    return word * xtal_hz / (1 << 16)
