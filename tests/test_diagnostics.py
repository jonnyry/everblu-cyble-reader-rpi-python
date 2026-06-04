"""Tests for everblu/diagnostics.py using a mocked SPI bus."""
from __future__ import annotations

from unittest.mock import patch

from everblu import cc1101_regs as R
from everblu.cc1101 import CC1101
from everblu.config import Config
from everblu.diagnostics import (
    DiagResult,
    check_frequency_roundtrip,
    check_patable_readback,
    check_spi_partnum_version,
    check_strobe_state_transitions,
    dump_config_registers,
)

from .test_cc1101 import FakeSpi


# --------------------------------------------------------------------------- #
# DiagResult
# --------------------------------------------------------------------------- #

def test_diag_result_str_pass():
    r = DiagResult("My check", True, "all good")
    s = str(r)
    assert "PASS" in s
    assert "My check" in s
    assert "all good" in s


def test_diag_result_str_fail():
    r = DiagResult("My check", False, "something wrong")
    s = str(r)
    assert "FAIL" in s
    assert "My check" in s


def test_diag_result_data_defaults_to_empty_dict():
    r = DiagResult("x", True)
    assert r.data == {}


# --------------------------------------------------------------------------- #
# check_spi_partnum_version
# --------------------------------------------------------------------------- #

def test_check_spi_partnum_version_pass():
    fake = FakeSpi()  # VERSION=0x14 which is in known_versions
    radio = CC1101(spi=fake)
    result = check_spi_partnum_version(radio)
    assert result.passed is True
    assert result.data["partnum"] == 0x00
    assert result.data["version"] == 0x14


def test_check_spi_partnum_version_fails_unknown_version():
    fake = FakeSpi()
    fake.status_regs[R.VERSION] = 0x99  # not in known set
    radio = CC1101(spi=fake)
    result = check_spi_partnum_version(radio)
    assert result.passed is False
    assert "not in known set" in result.detail


def test_check_spi_partnum_version_fails_all_zeros():
    fake = FakeSpi()
    fake.status_regs[R.VERSION] = 0x00
    fake.status_regs[R.PARTNUM] = 0x00
    radio = CC1101(spi=fake)
    result = check_spi_partnum_version(radio)
    # PARTNUM=0 is correct but VERSION=0 is not in known set -> FAIL
    assert result.passed is False
    assert "floating" in result.detail


def test_check_spi_partnum_version_fails_all_ones():
    fake = FakeSpi()
    fake.status_regs[R.VERSION] = 0xFF
    fake.status_regs[R.PARTNUM] = 0xFF
    radio = CC1101(spi=fake)
    result = check_spi_partnum_version(radio)
    assert result.passed is False
    assert "CSN" in result.detail or "wiring" in result.detail.lower()


# --------------------------------------------------------------------------- #
# check_patable_readback
# --------------------------------------------------------------------------- #

def test_check_patable_readback_pass():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    result = check_patable_readback(radio)
    assert result.passed is True
    assert result.data["wrote"] == result.data["read"]


def test_check_patable_readback_fail_on_mismatch():
    fake = FakeSpi()

    original_xfer2 = fake.xfer2

    def corrupt_patable(data):
        reply = original_xfer2(data)
        header = data[0]
        # Corrupt burst reads of PATABLE
        if (header & 0xC0) == 0xC0 and (header & 0x3F) == R.PATABLE:
            return [reply[0]] + [0x00] * (len(reply) - 1)
        return reply

    fake.xfer2 = corrupt_patable
    radio = CC1101(spi=fake)
    result = check_patable_readback(radio)
    assert result.passed is False


# --------------------------------------------------------------------------- #
# check_strobe_state_transitions
# --------------------------------------------------------------------------- #

def test_check_strobe_state_transitions_pass():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    with patch("everblu.diagnostics.time.sleep"):
        result = check_strobe_state_transitions(radio)
    assert result.passed is True
    assert result.data["idle"] == 0x01
    assert result.data["rx"] in (0x0D, 0x0E, 0x0F)
    assert result.data["idle2"] == 0x01


# --------------------------------------------------------------------------- #
# check_frequency_roundtrip
# --------------------------------------------------------------------------- #

def test_check_frequency_roundtrip_pass():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    cfg = Config()
    result = check_frequency_roundtrip(radio, cfg)
    assert result.passed is True
    assert result.data["error_hz"] < 500


def test_check_frequency_roundtrip_records_target_and_readback():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    cfg = Config()
    result = check_frequency_roundtrip(radio, cfg)
    assert result.data["target"] == cfg.radio.frequency_hz
    assert abs(result.data["readback"] - cfg.radio.frequency_hz) < 500


# --------------------------------------------------------------------------- #
# dump_config_registers
# --------------------------------------------------------------------------- #

def test_dump_config_registers_always_passes():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    result = dump_config_registers(radio)
    assert result.passed is True


def test_dump_config_registers_returns_47_bytes():
    fake = FakeSpi()
    radio = CC1101(spi=fake)
    result = dump_config_registers(radio)
    assert len(result.data["registers"]) == 47  # 0x2F = CFG_REGISTER_COUNT
