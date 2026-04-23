"""Radian protocol primitives used by Itron EverBlu Cyble meters.

Ported from the neutrinus/everblu-meters C reference (utils.c, cc1101.c).
This module is pure Python and has no hardware dependencies so it is
unit-testable.

Protocol overview
-----------------
To read the meter the collector:

1. Transmits a ~2 second wake-up preamble (0x55 bytes) at 2.4 kbps, with
   the CC1101 in fixed-length/no-sync "raw" mode.
2. Transmits a 39-byte request frame consisting of
     - a 9-byte sync pattern,
     - a 19-byte payload (message type, year, serial, CRC-Kermit),
       asynchronously serial-encoded: each source byte is bit-reversed,
       preceded by one 0 start bit, and followed by three 1 stop bits.
3. Receives a short ACK frame, then a long (~124 byte) data frame that
   contains the index (litres), battery months remaining, the configured
   business-hours window, and the read counter.
4. Decodes the received bits: the meter transmits at 2.4 kbps but the
   CC1101 is clocked at 9.59 kbps, producing 4x oversampling plus
   start/stop framing which must be stripped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# CRC-Kermit (same flavour as libcrc / crc_kermit)
# ---------------------------------------------------------------------------

_CRC_POLY = 0x8408
_CRC_INIT = 0x0000

_CRC_TABLE: list[int] = []


def _build_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = 0
        c = i
        for _ in range(8):
            if (crc ^ c) & 0x0001:
                crc = (crc >> 1) ^ _CRC_POLY
            else:
                crc >>= 1
            c >>= 1
        table.append(crc)
    return table


def crc_kermit(data: bytes) -> int:
    """Compute the 16-bit CRC-Kermit of ``data``.

    The implementation matches libcrc's ``crc_kermit`` which swaps the
    output bytes, returning (low<<8) | high.
    """
    global _CRC_TABLE
    if not _CRC_TABLE:
        _CRC_TABLE = _build_crc_table()
    crc = _CRC_INIT
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    low = (crc & 0xFF00) >> 8
    high = (crc & 0x00FF) << 8
    return (low | high) & 0xFFFF


# ---------------------------------------------------------------------------
# Async-serial 1-start / 3-stop encoding with per-byte bit reversal
# ---------------------------------------------------------------------------

def encode2serial_1_3(data: bytes) -> bytes:
    """Encode ``data`` as a bit stream with 1 start bit (0) and 3 stop
    bits (1) around each byte, with the byte's bits emitted LSB-first
    (i.e. each source byte is bit-reversed relative to MSB-first).

    The result is packed into whole bytes and padded with trailing 1 bits
    plus a final 0xFF filler, matching the C reference.
    """
    out_bits: list[int] = []
    for byte in data:
        # Start bit
        out_bits.append(0)
        # Data bits, LSB first
        for bit in range(8):
            out_bits.append((byte >> bit) & 1)
        # 3 stop bits
        out_bits.extend([1, 1, 1])

    # Pad to byte boundary with stop (1) bits
    while len(out_bits) % 8:
        out_bits.append(1)

    # Pack MSB-first into bytes, same as the C bit emitter.
    result = bytearray()
    for i in range(0, len(out_bits), 8):
        b = 0
        for j, bit in enumerate(out_bits[i:i + 8]):
            if bit:
                b |= 1 << (7 - j)
        result.append(b)
    # C code appends an extra 0xFF filler byte.
    result.append(0xFF)
    return bytes(result)


# ---------------------------------------------------------------------------
# Master request frame
# ---------------------------------------------------------------------------

SYNC_PATTERN = bytes((0x50, 0x00, 0x00, 0x00, 0x03, 0xFF, 0xFF, 0xFF, 0xFF))

# Template for the 19-byte payload. Indices 4..7 are filled with year and
# serial, indices 17..18 hold the CRC. Bytes 8..16 are fixed "read index"
# request opcodes lifted from the C reference.
_PAYLOAD_TEMPLATE = bytearray(
    (0x13, 0x10, 0x00, 0x45,
     0xFF, 0xFF, 0xFF, 0xFF,  # year + serial placeholders
     0x00, 0x45, 0x20, 0x0A, 0x50, 0x14, 0x00, 0x0A, 0x40,
     0xFF, 0xFF)  # CRC placeholders
)


def build_payload(year: int, serial: int) -> bytes:
    """Build the 19-byte Radian master-request payload with CRC.

    ``year`` is the last two digits of the manufacture year (e.g. 11 for
    a meter built in 2011). ``serial`` is a 24-bit integer.
    """
    if not 0 <= year <= 0xFF:
        raise ValueError("year must fit in one byte")
    if not 0 <= serial <= 0xFFFFFF:
        raise ValueError("serial must fit in 24 bits")
    payload = bytearray(_PAYLOAD_TEMPLATE)
    payload[4] = year & 0xFF
    payload[5] = (serial >> 16) & 0xFF
    payload[6] = (serial >> 8) & 0xFF
    payload[7] = serial & 0xFF
    crc = crc_kermit(bytes(payload[:-2]))
    payload[17] = (crc >> 8) & 0xFF
    payload[18] = crc & 0xFF
    return bytes(payload)


def make_master_request(year: int, serial: int) -> bytes:
    """Return the full request frame to transmit after the wake-up burst.

    Structure: 9-byte sync pattern, followed by the async-serial-encoded
    19-byte payload (plus trailing filler), matching the upstream C
    ``Make_Radian_Master_req`` function.
    """
    payload = build_payload(year, serial)
    return SYNC_PATTERN + encode2serial_1_3(payload)


# ---------------------------------------------------------------------------
# 4x oversampled start/stop decode
# ---------------------------------------------------------------------------

def decode_4bitpbit(raw: bytes) -> bytes:
    """Reverse of the meter's transmission encoding.

    The RF stream is captured at ~4x the symbol rate, so each transmitted
    bit appears as ~4 identical samples. Ported line-for-line from the
    upstream C ``decode_4bitpbit_serial`` so the resulting byte layout
    matches the field-proven reference (including the quirk that the
    start bit becomes the LSB of the decoded byte).
    """
    if not raw:
        return b""

    decoded = bytearray([0])
    dest_bit = 0
    dest_byte = 0
    bit_pol = raw[0] & 0x80  # 0x00 or 0x80
    bit_cnt = 0
    bit_cnt_flush = 0

    for byte in raw:
        cur = byte
        for _ in range(8):
            sample = cur & 0x80
            if sample == bit_pol:
                bit_cnt += 1
            elif bit_cnt == 1:
                # Single-sample glitch: treat as part of previous run.
                bit_pol = sample
                bit_cnt = bit_cnt_flush + 1
            else:
                bit_cnt_flush = bit_cnt
                n_bits = (bit_cnt + 2) // 4
                bit_cnt_flush -= n_bits * 4
                for _k in range(n_bits):
                    if dest_bit < 8:
                        decoded[dest_byte] = (
                            (decoded[dest_byte] >> 1) | (0x80 if bit_pol else 0x00)
                        ) & 0xFF
                    dest_bit += 1
                    if dest_bit == 10 and not bit_pol:
                        # Stop-bit error: abort and return what we have.
                        return bytes(decoded[:dest_byte])
                    if dest_bit >= 11 and not bit_pol:
                        dest_bit = 0
                        dest_byte += 1
                        decoded.append(0)
                bit_pol = sample
                bit_cnt = 1
            cur = (cur << 1) & 0xFF
    return bytes(decoded[:dest_byte])


# ---------------------------------------------------------------------------
# Meter report parsing
# ---------------------------------------------------------------------------

@dataclass
class MeterReading:
    liters: Optional[int] = None
    reads_counter: Optional[int] = None
    battery_months: Optional[int] = None
    window_start_hour: Optional[int] = None
    window_end_hour: Optional[int] = None
    meter_id: Optional[str] = None  # Meter identifier string
    additional_readings: list[int] = field(default_factory=list)  # Additional 32-bit values
    raw: bytes = b""

    def is_valid(self) -> bool:
        return self.liters is not None


def parse_meter_report(decoded: bytes) -> MeterReading:
    """Extract the documented fields from a decoded meter frame.

    Byte offsets follow the upstream C ``parse_meter_report`` function.
    """
    r = MeterReading(raw=decoded)
    if len(decoded) >= 30:
        # 32-bit little-endian litres at offset 18
        r.liters = int.from_bytes(decoded[18:22], "little")
    if len(decoded) >= 49:
        r.reads_counter = decoded[48]
        r.battery_months = decoded[31]
        r.window_start_hour = decoded[44]
        r.window_end_hour = decoded[45]
    # Extract meter ID string (around offset 32, typically 9 bytes)
    if len(decoded) >= 42:
        # Look for ASCII string around offset 32
        id_start = 32
        id_end = min(42, len(decoded))
        potential_id = decoded[id_start:id_end]
        # Extract printable ASCII characters
        id_bytes = []
        for b in potential_id:
            if 32 <= b <= 126:  # Printable ASCII
                id_bytes.append(b)
            elif id_bytes:  # Stop at first non-printable after starting
                break
        if len(id_bytes) >= 3:
            r.meter_id = bytes(id_bytes).decode('ascii', errors='ignore')[::-1]
    
    # Extract additional 32-bit readings (starting around offset 70)
    # These may be historical readings or other meter data
    reading_offset = 70
    while reading_offset + 4 <= len(decoded):
        # Stop if we hit padding (0x80 bytes) or end of meaningful data
        if decoded[reading_offset:reading_offset+4] == b'\x80\x80\x80\x80':
            break
        try:
            reading = int.from_bytes(decoded[reading_offset:reading_offset+4], "little")
            # Only include reasonable values (filter out obvious garbage)
            if 0 < reading < 10000000:  # Similar range to main liters reading
                r.additional_readings.append(reading)
        except (ValueError, OverflowError):
            pass
        reading_offset += 4
        # Limit to reasonable number of readings
        if len(r.additional_readings) >= 10:
            break
    
    return r
