#!/usr/bin/env python3
# =============================================================================
# tools/append_whatif_row.py
# Appends one row (CSMA combination + measured KPIs) to the what-if dataset.
# Creates the file with a header on first call. Skips (no-op) if the given id
# is already present, so a re-run after a crash never double-writes a row.
#
# Usage:
#   python3 tools/append_whatif_row.py \
#       --dataset what-if/dataset.csv \
#       --id 7 --min-be 0 --max-be 4 --max-backoff 4 --max-frame-retries 3 \
#       --metrics results/id_7/metrics.csv
# =============================================================================

import argparse
import csv
import os
import sys

COMBO_FIELDS = ["id", "CSMA_MIN_BE", "CSMA_MAX_BE", "CSMA_MAX_BACKOFF", "CSMA_MAX_FRAME_RETRIES"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--min-be", required=True)
    parser.add_argument("--max-be", required=True)
    parser.add_argument("--max-backoff", required=True)
    parser.add_argument("--max-frame-retries", required=True)
    parser.add_argument("--metrics", required=True, help="Path to the round's metrics.csv")
    args = parser.parse_args()

    if not os.path.exists(args.metrics):
        print(f"✗ metrics file not found: {args.metrics}", file=sys.stderr)
        sys.exit(1)

    with open(args.metrics, newline="") as f:
        metric_row = next(csv.DictReader(f))

    combo_row = {
        "id": args.id,
        "CSMA_MIN_BE": args.min_be,
        "CSMA_MAX_BE": args.max_be,
        "CSMA_MAX_BACKOFF": args.max_backoff,
        "CSMA_MAX_FRAME_RETRIES": args.max_frame_retries,
    }
    # Combo fields always win — a metrics.csv column that happens to be named
    # "id" (or any other combo field name) must never clobber it.
    metric_fields = [k for k in metric_row.keys() if k not in COMBO_FIELDS]
    fieldnames = COMBO_FIELDS + metric_fields
    row = {k: metric_row[k] for k in metric_fields}
    row.update(combo_row)

    file_exists = os.path.exists(args.dataset)
    if file_exists:
        with open(args.dataset, newline="") as f:
            existing_ids = {r["id"] for r in csv.DictReader(f)}
        if args.id in existing_ids:
            print(f"  → id={args.id} already in {args.dataset}, skipping append")
            return

    os.makedirs(os.path.dirname(os.path.abspath(args.dataset)), exist_ok=True)
    write_header = not file_exists or os.path.getsize(args.dataset) == 0
    with open(args.dataset, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"  ✓ Appended id={args.id} to {args.dataset}")


if __name__ == "__main__":
    main()
