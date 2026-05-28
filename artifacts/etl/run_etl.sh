#!/bin/sh
set -e

echo "=== WBBAW ETL ==="
echo "Run date: ${RUN_DATE:-$(date +%Y-%m-%d)}"
echo "Mode:     ${ETL_MODE:-INCREMENTAL}"
echo ""

echo "--- Step 1: Extract ---"
python wbbxtr.py
EXTRACT_RC=$?

if [ "$EXTRACT_RC" -gt 4 ]; then
    echo "Extract failed (RC=$EXTRACT_RC). Aborting."
    exit $EXTRACT_RC
fi

if [ "$EXTRACT_RC" -eq 4 ]; then
    echo "Extract produced 0 records or warnings. Checking staging file..."
    if [ ! -s "${STAGE_PATH:-/tmp/wbbaw_stage.jsonl}" ]; then
        echo "No staged records. Skipping load."
        exit 0
    fi
fi

echo ""
echo "--- Step 2: Load ---"
python wbbldr.py
LOAD_RC=$?

echo ""
echo "=== ETL complete (RC=$LOAD_RC) ==="
exit $LOAD_RC
