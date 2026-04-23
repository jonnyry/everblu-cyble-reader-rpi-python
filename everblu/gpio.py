"""Thin GPIO wrapper for reading GDO0 / GDO2 on the Raspberry Pi.

Uses ``lgpio`` which is the supported library on Raspberry Pi 5
(``RPi.GPIO`` does not work on the Pi 5's new RP1 I/O controller).
"""
from __future__ import annotations

import time
from typing import Optional


class GPIOError(RuntimeError):
    pass


class GPIO:
    """Minimal input-only GPIO helper.

    Parameters
    ----------
    chip : int
        gpiochip number (0 for the Pi 5 on-board header).
    pins : iterable[int]
        BCM pin numbers to claim as inputs.
    backend : object | None
        Optional injected ``lgpio``-like module for testing / dry-run.
    """

    def __init__(self, chip: int, pins, backend=None) -> None:
        self._pins = tuple(pins)
        self._handle = None
        if backend is None:
            try:
                import lgpio  # type: ignore
            except ImportError as exc:  # pragma: no cover
                raise GPIOError(
                    "lgpio not installed; `pip install lgpio` (required on Pi 5)"
                ) from exc
            self._lg = lgpio
        else:
            self._lg = backend
        self._handle = self._lg.gpiochip_open(chip)
        for pin in self._pins:
            self._lg.gpio_claim_input(self._handle, pin)

    def read(self, pin: int) -> int:
        return self._lg.gpio_read(self._handle, pin)

    def wait_high(self, pin: int, timeout_s: float) -> bool:
        """Poll ``pin`` until it reads 1 or the timeout expires."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.read(pin):
                return True
            time.sleep(0.0005)
        return False

    def wait_low(self, pin: int, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self.read(pin):
                return True
            time.sleep(0.0005)
        return False

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._lg.gpiochip_close(self._handle)
            except Exception:
                pass
            self._handle = None

    def __enter__(self) -> "GPIO":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
