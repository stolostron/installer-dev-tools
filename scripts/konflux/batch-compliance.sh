#!/usr/bin/env bash

show_help() {
    cat << EOF
Usage: batch-compliance.sh [OPTIONS] <application1> <application2> ...

Run compliance checks for multiple Konflux applications in parallel

ARGUMENTS:
    <application>    One or more application names to check (e.g., acm-215 mce-210)

OPTIONS:
    --debug          Enable debug logging output
    --retrigger      Retrigger failed components automatically
    -h, --help       Show this help message

EXAMPLES:
    batch-compliance.sh cluster-proxy-mce-210 cluster-proxy-addon-mce-210
    batch-compliance.sh acm-215 mce-210
    batch-compliance.sh --debug acm-215 mce-210
    batch-compliance.sh --retrigger mce-210 mce-29 mce-28 mce-27 mce-26
    batch-compliance.sh --retrigger acm-215 acm-214 acm-213 acm-212 acm-211 mce-210 mce-29 mce-28 mce-27 mce-26

NOTES:
    - Results are saved to logs/<application>-log.txt
    - Errors are saved to logs/<application>-error.txt
    - Compliance CSV files are saved to data/<application>-compliance.csv
EOF
}

cleanup() {
    echo "Killing background processes: $(jobs -p)"
    kill $(jobs -p)
}

trap cleanup SIGINT SIGTERM

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse options
debug_flag=""
retrigger_flag=""
apps=()
for arg in "$@"; do
    case $arg in
        -h|--help)
            show_help
            exit 0
            ;;
        --debug)
            debug_flag="--debug"
            ;;
        --retrigger)
            retrigger_flag="--retrigger"
            ;;
        *)
            apps+=("$arg")
            ;;
    esac
done

# Check if any applications provided
if [[ ${#apps[@]} -eq 0 ]]; then
    echo "Error: No applications specified"
    echo ""
    show_help
    exit 1
fi

mkdir -p logs

for app in "${apps[@]}"; do
    echo "Executing $SCRIPT_DIR/compliance.sh $debug_flag $retrigger_flag $app"
    "$SCRIPT_DIR/compliance.sh" $debug_flag $retrigger_flag $app > logs/$app-log.txt 2> logs/$app-error.txt &
done

echo "Waiting for all processes to complete"
wait
echo "Done"
