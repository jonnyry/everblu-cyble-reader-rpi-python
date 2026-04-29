#!/bin/bash
#
# cron_read_meter.sh - Run meter read for cron jobs
# Outputs JSON to log file, with errors wrapped in JSON format
# Then regenerates charts and publishes them to ~/www
#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${SCRIPT_DIR}/meter_config.env"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/readings.log}"
CHART_OUT="${CHART_OUT:-$SCRIPT_DIR/chart_out}"
WWW_DIR="${WWW_DIR:-$HOME/www}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Missing config file: $CONFIG_FILE" >&2
    exit 1
fi
source "$CONFIG_FILE"
: "${YEAR:?YEAR is not set in $CONFIG_FILE}"
: "${SERIAL:?SERIAL is not set in $CONFIG_FILE}"

get_timestamp() {
    date +"%Y-%m-%dT%H:%M:%S%z"
}
wrap_error() {
    local error_message="$1"
    local timestamp
    timestamp=$(get_timestamp)
    local escaped
    escaped=$(echo "$error_message" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
    python3 -c "import sys,json; d={'timestamp':'${timestamp}','error':$escaped}; print(json.dumps(d, indent=2))"
}

# --- 1. Take the reading ---
stdout=$(mktemp)
stderr=$(mktemp)
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/read_meter.py" --year "$YEAR" --serial "$SERIAL" --json --raw >"$stdout" 2>"$stderr"
exit_code=$?
if [ $exit_code -eq 0 ]; then
    cat "$stdout"
else
    wrap_error "$(cat "$stderr")"
fi >> "$LOG_FILE"
rm -f "$stdout" "$stderr"

# --- 2. Regenerate charts ---
mkdir -p "$CHART_OUT"
if ! "$PROJECT_DIR/.venv/bin/python" "${PROJECT_DIR}/scripts/water_chart.py" --log-file "$LOG_FILE" --output-dir "$CHART_OUT" >/dev/null; then
    echo "Chart generation failed" >&2
    exit 1
fi

# --- 3. Publish to ~/www ---
mkdir -p "$WWW_DIR"
cp "$CHART_OUT"/index.html \
   "$CHART_OUT"/water_usage_week.svg \
   "$CHART_OUT"/water_usage_month.svg \
   "$WWW_DIR"/
