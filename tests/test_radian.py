"""Tests for the Radian protocol primitives.

Several reference values are derived by running the original
C code (or equivalent libcrc functions) against known inputs.
"""
from __future__ import annotations

from everblu.radian import (
    SYNC_PATTERN,
    build_payload,
    crc_kermit,
    decode_4bitpbit,
    encode2serial_1_3,
    make_master_request,
    parse_meter_report,
)


# ---------------------------------------------------------------------------
# CRC-Kermit known-answers
# ---------------------------------------------------------------------------

def test_crc_kermit_empty():
    assert crc_kermit(b"") == 0


def test_crc_kermit_known_123456789():
    # Standard CRC-Kermit test vector. The C reference stores the result
    # as bytes ((crc>>8)&0xFF, crc&0xFF) which yields the on-wire bytes
    # (0x89, 0x21) -- matching what this function returns when big-endian
    # serialised.
    assert crc_kermit(b"123456789") == 0x8921


def test_crc_kermit_single_byte():
    # libcrc/crc_kermit(b"\x00") -> 0x0000
    assert crc_kermit(b"\x00") == 0x0000


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------

def test_build_payload_layout():
    p = build_payload(year=15, serial=0x031595) # = 202517
    # Fixed preamble
    assert p[0:4] == bytes((0x13, 0x10, 0x00, 0x45))
    # Year + 24-bit serial big-endian in bytes 4..7
    assert p[4] == 15
    assert p[5:8] == bytes((0x03, 0x15, 0x95))
    # Middle fixed opcodes
    assert p[8:17] == bytes((0x00, 0x45, 0x20, 0x0A, 0x50, 0x14, 0x00, 0x0A, 0x40))
    # CRC is present (not the placeholder 0xFFFF)
    assert (p[17], p[18]) != (0xFF, 0xFF)
    # CRC verifies
    assert crc_kermit(p[:17]) == (p[17] << 8) | p[18]
    assert len(p) == 19


def test_build_payload_rejects_out_of_range():
    import pytest
    with pytest.raises(ValueError):
        build_payload(year=256, serial=1)
    with pytest.raises(ValueError):
        build_payload(year=11, serial=1 << 24)


# ---------------------------------------------------------------------------
# Async-serial encoding
# ---------------------------------------------------------------------------

def test_encode_single_zero_byte():
    # One input byte. Expected bit stream (start=0, 8 data zeros, 3 stop
    # ones, then 4 pad-to-byte-boundary ones, then the 0xFF filler):
    #   0 0000 0000 111 1111  |  11111111
    # Packed MSB-first into two content bytes + filler:
    #   0x00  0x7F  0xFF
    out = encode2serial_1_3(b"\x00")
    assert out == b"\x00\x7F\xFF"


def test_encode_single_0xff_byte():
    # start=0, 8 data=1, 3 stops=1 -> 0 11111111 111 = 0 1111 1111 1111
    # = 0x7F 0xFF, then 0xFF filler.
    out = encode2serial_1_3(b"\xFF")
    assert out == b"\x7F\xFF\xFF"


# ---------------------------------------------------------------------------
# make_master_request smoke test
# ---------------------------------------------------------------------------

def test_make_master_request_starts_with_sync_pattern():
    req = make_master_request(15, 202517)
    assert req[: len(SYNC_PATTERN)] == SYNC_PATTERN
    # Expected total length: 9 sync + ceil(19*12/8)+1 fill + 0xFF
    # Each of the 19 payload bytes expands to 1 start + 8 data + 3 stops
    # = 12 bits => 228 bits, padded to 232 = 29 bytes, plus trailing 0xFF.
    assert len(req) == 9 + 29 + 1


# ---------------------------------------------------------------------------
# parse_meter_report
# ---------------------------------------------------------------------------

def test_parse_meter_report_short():
    r = parse_meter_report(b"\x00" * 10)
    assert not r.is_valid()
    assert r.liters is None


def test_parse_meter_report_full():
    buf = bytearray(64)
    # liters = 123456 LE at offset 18
    buf[18:22] = (123456).to_bytes(4, "little")
    buf[31] = 42     # battery months
    buf[44] = 8      # window start
    buf[45] = 16     # window end
    buf[48] = 77     # reads counter
    r = parse_meter_report(bytes(buf))
    assert r.is_valid()
    assert r.liters == 123456
    assert r.battery_months == 42
    assert r.window_start_hour == 8
    assert r.window_end_hour == 16
    assert r.reads_counter == 77


# ---------------------------------------------------------------------------
# decode_4bitpbit sanity: does not crash on garbage / empty
# ---------------------------------------------------------------------------

def test_decode_empty():
    assert decode_4bitpbit(b"") == b""


def test_decode_all_zeros():
    # No polarity transitions -> no bytes decoded.
    assert decode_4bitpbit(b"\x00" * 16) == b""


def test_decode_alternating_fixed_length():
    # Smoke test: should not raise and should return bytes().
    out = decode_4bitpbit(b"\xAA" * 32)
    assert isinstance(out, bytes)
