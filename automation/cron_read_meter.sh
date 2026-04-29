#!/bin/bash
#
# cron_read_meter.sh - Run meter read for cron jobs
# Outputs JSON to readings.log; errors written to errors.log
# Then regenerates charts and publishes them to ~/www
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${SCRIPT_DIR}/meter_config.env"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/readings.log}"
ERROR_LOG="${ERROR_LOG:-$SCRIPT_DIR/error.log}"
CHART_OUT="${CHART_OUT:-$SCRIPT_DIR/chart_out}"
WWW_DIR="${WWW_DIR:-$HOME/www}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Missing config file: $CONFIG_FILE" >&2
    exit 1
fi
source "$CONFIG_FILE"
: "${YEAR:?YEAR is not set in $CONFIG_FILE}"
: "${SERIAL:?SERIAL is not set in $CONFIG_FILE}"

# --- 1. Take the reading ---
stdout=$(mktemp)
stderr=$(mktemp)
"$PROJECT_DIR/run.sh" read_meter --year "$YEAR" --serial "$SERIAL" --json --raw >"$stdout" 2>"$stderr"
exit_code=$?
if [ $exit_code -eq 0 ]; then
    cat "$stdout" >> "$LOG_FILE"
else
    cat "$stderr" >> "$ERROR_LOG"
fi
rm -f "$stdout" "$stderr"

# --- 2. Regenerate charts ---
mkdir -p "$CHART_OUT"
if ! "$PROJECT_DIR/run.sh" chart --log-file "$LOG_FILE" --output-dir "$CHART_OUT" >/dev/null; then
    echo "Chart generation failed" >&2
    exit 1
fi

# --- 3. Publish to ~/www ---
mkdir -p "$WWW_DIR"
cp "$CHART_OUT"/* "$WWW_DIR"/
