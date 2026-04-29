#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if install.sh has been run
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "ERROR: Virtual environment not found."
    echo "Please run the installation script first:"
    echo "    ./install.sh"
    exit 1
fi

# Warn if user is not in the spi/gpio groups
if ! groups | grep -q '\(spi\|gpio\)'; then
    echo "WARNING: Your user is not in the spi or gpio groups."
    echo "The installation may not be complete. Please run:"
    echo "    ./install.sh"
    echo "Then log out and back in (or reboot) for group membership to take effect."
fi

if [ $# -lt 1 ]; then
    echo "Usage: ./run.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  diag        - Run hardware diagnostics"
    echo "  read_meter  - Read the water meter"
    echo "  freq_scan   - Sweep frequency to find calibration offset"
    echo "  chart       - Generate charts from log file"
    echo "  unit_test   - Run unit tests"
    exit 1
fi

COMMAND=$1
shift

case "$COMMAND" in
    diag)
        "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/diag.py" "$@"
        ;;
    read_meter)
        "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/read_meter.py" "$@"
        ;;
    freq_scan)
        "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/freq_scan.py" "$@"
        ;;
    chart)
        "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/water_chart.py" "$@"
        ;;
    unit_test)
        "$SCRIPT_DIR/.venv/bin/python" -m pytest "$SCRIPT_DIR/tests/" "$@"
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Valid commands: diag, read_meter, freq_scan, chart, unit_test"
        exit 1
        ;;
esac
