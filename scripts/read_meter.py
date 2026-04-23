"""CLI: read the EverBlu Cyble meter and print the decoded index."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everblu.config import Config
from everblu.reader import MeterReader, ReaderError, in_listen_window


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True,
                   help="last 2 digits of the meter manufacture year")
    p.add_argument("--serial", type=int, required=True,
                   help="meter serial (middle segment of label, no leading 0)")
    p.add_argument("--freq-offset-hz", type=int, default=0,
                   help="CC1101 frequency trim in Hz")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--retry-delay", type=float, default=5.0)
    p.add_argument("--force", action="store_true",
                   help="try even outside the meter listen window")
    p.add_argument("--raw", action="store_true",
                   help="include the raw decoded frame (hex) in output")
    p.add_argument("--json", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg = Config()
    cfg.meter.year = args.year
    cfg.meter.serial = args.serial
    cfg.radio.freq_offset_hz = args.freq_offset_hz

    if not args.force and not in_listen_window(cfg):
        print(
            f"WARNING: outside meter listen window "
            f"({cfg.meter.listen_start}-{cfg.meter.listen_end}, Mon-Sat). "
            f"Meter will likely not respond. Pass --force to try anyway.",
            file=sys.stderr,
        )

    last_exc = None
    with MeterReader(cfg) as reader:
        for attempt in range(1, args.retries + 1):
            try:
                reading = reader.read(force=args.force)
                break
            except ReaderError as exc:
                last_exc = exc
                print(f"attempt {attempt}/{args.retries} failed: {exc}",
                      file=sys.stderr)
                if attempt < args.retries:
                    time.sleep(args.retry_delay)
        else:
            print(f"FAIL: all attempts exhausted. last error: {last_exc}",
                  file=sys.stderr)
            return 1

    payload = {
        "liters": reading.liters,
        "reads_counter": reading.reads_counter,
        "battery_months": reading.battery_months,
        "window_start_hour": reading.window_start_hour,
        "window_end_hour": reading.window_end_hour,
        "valid": reading.is_valid(),
    }
    if args.raw:
        payload["raw_hex"] = reading.raw.hex()

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Meter {args.year}-{args.serial:08d}")
        print(f"  liters:          {reading.liters}")
        print(f"  reads_counter:   {reading.reads_counter}")
        print(f"  battery_months:  {reading.battery_months}")
        print(f"  listen window:   {reading.window_start_hour}h-"
              f"{reading.window_end_hour}h")
        if args.raw:
            print(f"  raw ({len(reading.raw)}B): {reading.raw.hex()}")

    return 0 if reading.is_valid() else 1


if __name__ == "__main__":
    sys.exit(main())
