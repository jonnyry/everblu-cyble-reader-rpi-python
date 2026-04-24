#!/bin/bash
#
# cron_read_meter.sh - Run meter read for cron jobs
# Outputs JSON to log file, with errors wrapped in JSON format
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/readings.log}"

# parameters
YEAR="${METER_YEAR}"
SERIAL="${METER_SERIAL}"

# Function to get ISO8601 timestamp
get_timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Function to wrap error in JSON
wrap_error() {
    local error_message="$1"
    local timestamp
    timestamp=$(get_timestamp)
    # Escape the error message for valid JSON and pretty-print
    local escaped
    escaped=$(echo "$error_message" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
    python3 -c "import sys,json; d={'timestamp':'${timestamp}','error':$escaped}; print(json.dumps(d, indent=2))"
}

# Run the meter read - capture stdout and stderr separately in one run
stdout=$(mktemp)
stderr=$(mktemp)

# Run script once: stdout -> file, stderr -> file
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/scripts/read_meter.py" --year "$YEAR" --serial "$SERIAL" --json --raw >"$stdout" 2>"$stderr"
exit_code=$?

if [ $exit_code -eq 0 ]; then
    # Success: output clean JSON from stdout
    cat "$stdout"
else
    # Failure: wrap stderr content in JSON error
    wrap_error "$(cat "$stderr")"
fi >> "$LOG_FILE"

# Cleanup
rm -f "$stdout" "$stderr"