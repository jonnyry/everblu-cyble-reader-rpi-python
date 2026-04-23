"""Configuration for meter identity, RF parameters and GPIO pin mapping.

Values default to the installation described in specification.md:
- Itron EverBlu Cyble Enhanced V2.1
- Serial on label: AA-BBBBBBB-CCC (manufactured MM/YYYY)
- CC1101 on Raspberry Pi via SPI0/CE0, GDO0=GPIO17, GDO2=GPIO27.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


# Middle segment of the label serial "AA-BBBBBBB-CCC", leading zero stripped
# per the upstream project's convention. Year byte is the last two digits of
# the manufacture year (2015 -> 15).
DEFAULT_METER_YEAR = 11
DEFAULT_METER_SERIAL = 1111111


@dataclass
class MeterConfig:
    year: int = DEFAULT_METER_YEAR
    serial: int = DEFAULT_METER_SERIAL
    # Business-hours window during which the meter wakes to listen.
    listen_start: time = time(6, 0)
    listen_end: time = time(18, 0)
    # Days of the week the meter listens (Mon=0 .. Sun=6). Default Mon-Sat.
    listen_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5)


@dataclass
class RadioConfig:
    # Base frequency in Hz. 433.82 MHz matches FREQ2/1/0=0x10/0xAF/0x75
    # computed against the 26 MHz TCXO on typical CC1101 modules.
    frequency_hz: int = 433_820_000
    xtal_hz: int = 26_000_000
    # SPI configuration.
    spi_bus: int = 0
    spi_device: int = 0  # CE0
    spi_speed_hz: int = 1_000_000
    # Optional per-module frequency trim, applied on top of frequency_hz.
    # Calibrated value for this specific CC1101 module, determined via
    # scripts/freq_scan.py: reliable lock from -30 kHz to -10 kHz; -15 kHz
    # sits in the middle of the band.
    freq_offset_hz: int = -15_000


@dataclass
class GPIOConfig:
    # BCM pin numbers
    gdo0_pin: int = 17
    gdo2_pin: int = 27
    chip: int = 0  # /dev/gpiochip0 on Pi 5


@dataclass
class Config:
    meter: MeterConfig = field(default_factory=MeterConfig)
    radio: RadioConfig = field(default_factory=RadioConfig)
    gpio: GPIOConfig = field(default_factory=GPIOConfig)
