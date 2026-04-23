"""CLI: sweep CC1101 frequency trim to find the meter's calibration offset.

Your CC1101 module's crystal may be slightly off nominal; this sweeps a
range of offsets around 433.82 MHz and attempts a read at each step,
reporting which offsets produced valid frames with the best RSSI.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everblu.config import Config
from everblu.reader import MeterReader, ReaderError


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--serial", type=int, required=True)
    p.add_argument("--start-hz", type=int, default=-60_000)
    p.add_argument("--stop-hz", type=int, default=60_000)
    p.add_argument("--step-hz", type=int, default=5_000)
    p.add_argument("--force", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = Config()
    cfg.meter.year = args.year
    cfg.meter.serial = args.serial

    successes = []
    offset = args.start_hz
    while offset <= args.stop_hz:
        cfg.radio.freq_offset_hz = offset
        with MeterReader(cfg) as reader:
            try:
                reading = reader.read(force=args.force)
                ok = reading.is_valid()
                rssi = reader.radio.rssi_dbm()
            except ReaderError as exc:
                ok = False
                rssi = None
                print(f"offset={offset:+d} Hz: fail ({exc})")
            else:
                if ok:
                    successes.append((offset, reading.liters, rssi))
                    print(f"offset={offset:+d} Hz: OK liters={reading.liters} rssi={rssi:.1f}")
                else:
                    print(f"offset={offset:+d} Hz: no valid frame")
        offset += args.step_hz
        time.sleep(1)  # give the meter a breather between reads

    if successes:
        print("\nSuccessful offsets:")
        for off, liters, rssi in successes:
            print(f"  {off:+d} Hz  liters={liters}  rssi={rssi:.1f} dBm")
        return 0
    print("\nNo offset yielded a valid frame.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
