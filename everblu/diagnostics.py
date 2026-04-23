"""Hardware diagnostics for the CC1101 + Raspberry Pi wiring.

Each check returns a ``DiagResult`` with a status and human-readable
detail. The CLI entry point is ``scripts/diag.py``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import cc1101_regs as R
from .cc1101 import CC1101
from .config import Config
from .gpio import GPIO


@dataclass
class DiagResult:
    name: str
    passed: bool
    detail: str = ""
    data: dict = field(default_factory=dict)

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.name}: {self.detail}"


def check_spi_partnum_version(radio: CC1101) -> DiagResult:
    """Read PARTNUM and VERSION. PARTNUM must be 0x00; VERSION in known set."""
    radio.reset()
    partnum = radio.partnum()
    version = radio.version()
    known_versions = {0x03, 0x04, 0x14, 0x17, 0x18}
    ok = partnum == 0x00 and version in known_versions
    hint = ""
    if partnum == 0x00 and version == 0x00:
        hint = " (all zero: MISO likely floating or disconnected)"
    elif partnum == 0xFF and version == 0xFF:
        hint = " (all ones: check CSN/SCK wiring or 3V3 power)"
    elif version not in known_versions:
        hint = f" (VERSION=0x{version:02X} not in known set {sorted(known_versions)})"
    return DiagResult(
        "CC1101 PARTNUM/VERSION",
        ok,
        f"PARTNUM=0x{partnum:02X} VERSION=0x{version:02X}{hint}",
        {"partnum": partnum, "version": version},
    )


def check_strobe_state_transitions(radio: CC1101) -> DiagResult:
    """SIDLE -> MARCSTATE=IDLE; SRX -> MARCSTATE=RX; back to IDLE."""
    radio.reset()
    radio.apply_default_config()

    radio.strobe(R.SIDLE)
    time.sleep(0.002)
    idle_state = radio.marcstate()
    radio.strobe(R.SRX)
    deadline = time.monotonic() + 0.1
    rx_state = 0
    while time.monotonic() < deadline:
        rx_state = radio.marcstate()
        if rx_state in (0x0D, 0x0E, 0x0F):
            break
    radio.strobe(R.SIDLE)
    time.sleep(0.002)
    idle2 = radio.marcstate()
    ok = idle_state == 0x01 and rx_state in (0x0D, 0x0E, 0x0F) and idle2 == 0x01
    return DiagResult(
        "Strobe & state transitions",
        ok,
        f"IDLE=0x{idle_state:02X} RX=0x{rx_state:02X} IDLE2=0x{idle2:02X}",
        {"idle": idle_state, "rx": rx_state, "idle2": idle2},
    )


def check_patable_readback(radio: CC1101) -> DiagResult:
    """Write PATABLE and read it back to confirm burst SPI works."""
    radio.reset()
    pattern = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    radio.write_burst(R.PATABLE, pattern)
    got = radio.dump_patable()
    ok = list(got) == pattern
    return DiagResult(
        "PATABLE write/read-back",
        ok,
        f"wrote={['0x%02X' % b for b in pattern]} read={['0x%02X' % b for b in got]}",
        {"wrote": pattern, "read": list(got)},
    )


def check_gdo_wiring(radio: CC1101, gpio: GPIO, cfg: Config) -> DiagResult:
    """Use IOCFG to drive GDO0/GDO2 to HW0 then HW1; verify Pi reads match."""
    radio.reset()
    pins = {"GDO0": (cfg.gpio.gdo0_pin, R.IOCFG0),
            "GDO2": (cfg.gpio.gdo2_pin, R.IOCFG2)}
    results: dict = {}
    all_ok = True
    detail_parts: list[str] = []
    for name, (pin, iocfg_reg) in pins.items():
        # 0x2F = HW to 0; 0x6F = HW to 1 (datasheet GDOx_CFG values)
        radio.write_reg(iocfg_reg, 0x2F)
        time.sleep(0.002)
        low = gpio.read(pin)
        radio.write_reg(iocfg_reg, 0x6F)
        time.sleep(0.002)
        high = gpio.read(pin)
        ok = (low == 0 and high == 1)
        all_ok &= ok
        results[name] = {"low": low, "high": high, "ok": ok}
        detail_parts.append(f"{name}(pin{pin}): low={low} high={high}")
    return DiagResult(
        "GDO0/GDO2 wiring",
        all_ok,
        "; ".join(detail_parts),
        results,
    )


def check_xosc_clock(radio: CC1101, gpio: GPIO, cfg: Config) -> DiagResult:
    """Route XOSC/192 to GDO0 and count edges over 10 ms. Expect ~1350."""
    radio.reset()
    # IOCFG0 = 0x3F routes XOSC/192 (~135.4 kHz for a 26 MHz xtal) to GDO0
    radio.write_reg(R.IOCFG0, 0x3F)
    pin = cfg.gpio.gdo0_pin

    transitions = 0
    prev = gpio.read(pin)
    start = time.perf_counter()
    duration = 0.010
    while time.perf_counter() - start < duration:
        cur = gpio.read(pin)
        if cur != prev:
            transitions += 1
            prev = cur
    elapsed = time.perf_counter() - start
    # Each full cycle is 2 transitions
    freq = transitions / (2 * elapsed) if elapsed > 0 else 0
    expected = cfg.radio.xtal_hz / 192
    # We expect to see *at least* a few kHz even under Python polling limits;
    # the Pi can't sample 135 kHz reliably from userspace, so accept any
    # non-zero toggle as success but warn if it's clearly off.
    ok = transitions > 10
    return DiagResult(
        "XOSC/192 clock on GDO0",
        ok,
        f"{transitions} edges in {elapsed*1000:.1f} ms (observed ~{freq/1000:.1f} kHz, "
        f"true {expected/1000:.1f} kHz; polling can undersample)",
        {"transitions": transitions, "elapsed_s": elapsed, "observed_hz": freq},
    )


def check_rssi_noise(radio: CC1101, cfg: Config) -> DiagResult:
    """Enter RX on the meter frequency, sample RSSI, report statistics."""
    radio.reset()
    radio.apply_default_config()
    if cfg.radio.freq_offset_hz:
        radio.set_frequency(
            cfg.radio.frequency_hz + cfg.radio.freq_offset_hz,
            cfg.radio.xtal_hz,
        )
    radio.enter_rx()
    samples = []
    start = time.perf_counter()
    while time.perf_counter() - start < 0.5:
        samples.append(radio.rssi_dbm())
        time.sleep(0.01)
    radio.strobe(R.SIDLE)
    lo, hi = min(samples), max(samples)
    avg = sum(samples) / len(samples)
    # Reasonable sanity: noise floor typically -90..-110 dBm, saturated ~0.
    ok = lo < -50 and len(samples) > 10
    return DiagResult(
        "RX noise floor (RSSI)",
        ok,
        f"min={lo:.1f} avg={avg:.1f} max={hi:.1f} dBm over {len(samples)} samples",
        {"min": lo, "avg": avg, "max": hi, "count": len(samples)},
    )


def check_frequency_roundtrip(radio: CC1101, cfg: Config) -> DiagResult:
    radio.reset()
    radio.apply_default_config()
    target = cfg.radio.frequency_hz
    radio.set_frequency(target, cfg.radio.xtal_hz)
    got = radio.get_frequency(cfg.radio.xtal_hz)
    err = abs(got - target)
    ok = err < 500  # less than 500 Hz quantisation error
    return DiagResult(
        "Frequency register programming",
        ok,
        f"wrote {target} Hz, read back {got:.0f} Hz (err {err:.0f} Hz)",
        {"target": target, "readback": got, "error_hz": err},
    )


def dump_config_registers(radio: CC1101) -> DiagResult:
    radio.reset()
    radio.apply_default_config()
    regs = radio.dump_config()
    pretty = " ".join(f"{b:02X}" for b in regs)
    return DiagResult(
        "Config register dump",
        True,
        f"{len(regs)} registers: {pretty}",
        {"registers": list(regs)},
    )


ALL_CHECKS: tuple[Callable, ...] = (
    check_spi_partnum_version,
    check_patable_readback,
    check_strobe_state_transitions,
    check_frequency_roundtrip,
    check_gdo_wiring,
    check_xosc_clock,
    check_rssi_noise,
    dump_config_registers,
)


def run_all(cfg: Config, radio: Optional[CC1101] = None,
            gpio: Optional[GPIO] = None) -> List[DiagResult]:
    own_radio = radio is None
    own_gpio = gpio is None
    if radio is None:
        radio = CC1101(
            bus=cfg.radio.spi_bus,
            device=cfg.radio.spi_device,
            speed_hz=cfg.radio.spi_speed_hz,
        )
    if gpio is None:
        gpio = GPIO(cfg.gpio.chip, (cfg.gpio.gdo0_pin, cfg.gpio.gdo2_pin))

    results: list[DiagResult] = []
    try:
        for check in ALL_CHECKS:
            # Dispatch based on the check's arg count.
            import inspect
            sig = inspect.signature(check)
            kwargs = {}
            params = list(sig.parameters)
            args = []
            for p in params:
                if p == "radio":
                    args.append(radio)
                elif p == "gpio":
                    args.append(gpio)
                elif p == "cfg":
                    args.append(cfg)
            try:
                results.append(check(*args, **kwargs))
            except Exception as exc:
                results.append(DiagResult(check.__name__, False, f"exception: {exc}"))
    finally:
        if own_radio:
            radio.close()
        if own_gpio:
            gpio.close()
    return results
