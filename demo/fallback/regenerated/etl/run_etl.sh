#!/bin/sh
set -e
echo "=== Regenerated WBBAW ETL ==="
echo "--- Step 1: Extract ---"
python extract.py
echo "--- Step 2: Load ---"
python load.py
echo "=== Complete ==="
