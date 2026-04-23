"""CLI: run the CC1101 + Raspberry Pi wiring diagnostic suite."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everblu.config import Config
from everblu.diagnostics import run_all


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--json", action="store_true", help="output JSON")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg = Config()
    try:
        results = run_all(cfg)
    except Exception as exc:
        print(f"FATAL: could not open hardware: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(
            [{"name": r.name, "passed": r.passed, "detail": r.detail, "data": r.data}
             for r in results],
            indent=2, default=str,
        ))
    else:
        for r in results:
            print(r)

    failed = [r for r in results if not r.passed]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
