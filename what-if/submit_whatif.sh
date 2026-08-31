#!/bin/bash
# =============================================================================
# submit_whatif.sh
# Pre-flight-checks that all required firmware is cached (run
# prebuild_firmware.py first if not), then submits one SLURM job per
# (combination, active topology) pair not already present in that topology's
# dataset_<topology>.csv (one dataset file per scenario).
#
# Usage:
#   bash submit_whatif.sh
#
# Monitor:
#   squeue -u mihoubrahma
#   tail -f logs/dataset/<id>_<topology>.out
# =============================================================================
set -euo pipefail

WHATIF_DIR="/home/mihoubrahma/cooja-sim/what-if"
COMBINATIONS_CSV="$WHATIF_DIR/combinations.csv"
LOGS_DIR="$WHATIF_DIR/logs/dataset"
# One dataset file per scenario: $WHATIF_DIR/dataset_<topology>.csv

# Per-topology SLURM overrides; unlisted topologies fall back to the DEFAULT_*
# values below (so adding a new topology to wi_common.py's ACTIVE_TOPOLOGIES
# doesn't strictly require editing this script).
declare -A SLURM_TIME=( [Sc4]="04:00:00" [Sc9]="01:30:00" )
declare -A SLURM_MEM=(  [Sc4]="8G"       [Sc9]="4G" )
DEFAULT_TIME="02:00:00"
DEFAULT_MEM="4G"
# ─────────────────────────────────────────────────────────────────────────────

mkdir -p "$LOGS_DIR"

echo "Started at: $(date)"

# ── Pre-flight: firmware must already be fully built ─────────────────────────
echo "Checking firmware cache..."
if ! (cd "$WHATIF_DIR" && python3 prebuild_firmware.py --check); then
    echo ""
    echo "ERROR: firmware cache is not ready. Run:"
    echo "  python3 $WHATIF_DIR/prebuild_firmware.py"
    echo "and wait for it to finish (0 failures) before submitting sim jobs."
    exit 1
fi

# ── Active topologies (single source of truth: wi_common.py) ────────────────
TOPOLOGIES=$(cd "$WHATIF_DIR" && python3 -c "from wi_common import ACTIVE_TOPOLOGIES; print(' '.join(ACTIVE_TOPOLOGIES))")
echo "Active topologies: $TOPOLOGIES"

TOTAL_COMBOS=$(tail -n +2 "$COMBINATIONS_CSV" | wc -l)
TOTAL_JOBS=$(( TOTAL_COMBOS * $(echo "$TOPOLOGIES" | wc -w) ))
echo "Combinations: $TOTAL_COMBOS   Topologies: $(echo $TOPOLOGIES | wc -w)   Max jobs: $TOTAL_JOBS"

# Get ids already done per topology (if resuming) — one dataset file per scenario
declare -A DONE_IDS
for topology in $TOPOLOGIES; do
    dataset_csv="$WHATIF_DIR/dataset_${topology}.csv"
    if [ -f "$dataset_csv" ]; then
        DONE_IDS[$topology]=$(tail -n +2 "$dataset_csv" | cut -d',' -f1 | sort -un)
    else
        DONE_IDS[$topology]=""
    fi
done

SUBMITTED=0
SKIPPED=0

while IFS=',' read -r id min_be max_be max_backoff max_frame_retries; do
    [ "$id" = "id" ] && continue
    max_frame_retries="${max_frame_retries//$'\r'/}"

    for topology in $TOPOLOGIES; do
        if echo "${DONE_IDS[$topology]}" | grep -qxF "$id"; then
            SKIPPED=$((SKIPPED + 1))
            continue
        fi

        slurm_time="${SLURM_TIME[$topology]:-$DEFAULT_TIME}"
        slurm_mem="${SLURM_MEM[$topology]:-$DEFAULT_MEM}"

        sbatch \
            --job-name="wi-${id}-${topology}" \
            --partition=main \
            --cpus-per-task=1 \
            --mem="$slurm_mem" \
            --time="$slurm_time" \
            --output="${LOGS_DIR}/${id}_${topology}.out" \
            --error="${LOGS_DIR}/${id}_${topology}.err" \
            --wrap="python3 $WHATIF_DIR/run_one_whatif_sim.py \
                --id $id --topology $topology \
                --min-be $min_be --max-be $max_be \
                --max-backoff $max_backoff --max-frame-retries $max_frame_retries"

        SUBMITTED=$((SUBMITTED + 1))
    done
done < "$COMBINATIONS_CSV"

echo ""
echo "Submitted : $SUBMITTED jobs"
echo "Skipped   : $SKIPPED (already done)"
echo ""
echo "Monitor   : squeue -u mihoubrahma"
echo "Progress  : wc -l $WHATIF_DIR/dataset_<topology>.csv"
echo "Logs      : tail -f $LOGS_DIR/<id>_<topology>.out"
