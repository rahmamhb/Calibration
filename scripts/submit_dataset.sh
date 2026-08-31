#!/bin/bash
# =============================================================================
# submit_dataset.sh
# Submits one SLURM job per combination in combinations.csv.
# Each job runs the full pipeline for one parameter set and appends
# its result to dataset.csv.
#
# Usage:
#   bash submit_dataset.sh
#
# Monitor:
#   squeue -u mihoubrahma
#   tail -f logs/dataset/<id>.out
# =============================================================================

# ── EDIT THESE ────────────────────────────────────────────────────────────────
PROJECT_DIR="/home/mihoubrahma/cooja-sim"
COMBINATIONS_CSV="$PROJECT_DIR/combinations.csv"
DATASET_CSV="$PROJECT_DIR/dataset.csv"
LOGS_DIR="$PROJECT_DIR/logs/dataset"
# ─────────────────────────────────────────────────────────────────────────────

mkdir -p "$LOGS_DIR"

START_TIME=$(date +%s)
echo "Started at: $(date)"

# Count total combinations
TOTAL=$(tail -n +2 "$COMBINATIONS_CSV" | wc -l)
echo "Submitting $TOTAL jobs..."

# Get IDs already done (if resuming)
if [ -f "$DATASET_CSV" ]; then
    DONE_IDS=$(tail -n +2 "$DATASET_CSV" | cut -d',' -f1 | sort -n)
else
    DONE_IDS=""
fi

SUBMITTED=0
SKIPPED=0

while IFS=',' read -r id rx_sens rssi_ip tr ple awgn; do
    # Skip header
    [ "$id" = "id" ] && continue

    # Strip any trailing \r from the last field
    awgn="${awgn//$'\r'/}"

    # Skip already done
    if echo "$DONE_IDS" | grep -qw "$id"; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Submit one job per combination
    sbatch \
        --job-name="cooja-sim-${id}" \
        --partition=main \
        --cpus-per-task=1 \
        --mem=4G \
        --time=03:00:00 \
        --output="${LOGS_DIR}/${id}.out" \
        --error="${LOGS_DIR}/${id}.err" \
        --wrap="python3 $PROJECT_DIR/run_one_sim.py \
            --id $id \
            --rx-sensitivity $rx_sens \
            --rssi-inflection-point $rssi_ip \
            --transmitting-range $tr \
            --path-loss-exponent $ple \
            --awgn-sigma $awgn"

    SUBMITTED=$((SUBMITTED + 1))

done < "$COMBINATIONS_CSV"

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))

echo ""
echo "Submitted : $SUBMITTED jobs"
echo "Skipped   : $SKIPPED (already done)"
echo "Submit time: ${ELAPSED}s"
echo ""
echo "Monitor   : squeue -u mihoubrahma"
echo "Progress  : wc -l $DATASET_CSV"
echo "Logs      : tail -f $LOGS_DIR/<id>.out"
echo ""
echo "When all jobs finish, get total simulation time with:"
echo "  sacct -u mihoubrahma --format=JobID,Start,End,Elapsed,State | grep COMPLETED | awk 'BEGIN{min=\"9999\"; max=\"0000\"} {if(\$2<min)min=\$2; if(\$3>max)max=\$3} END{print \"First start:\",min,\"\\nLast end:\",max}'"
