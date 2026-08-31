#!/bin/bash
# =============================================================================
# what-if/run_sweep.sh
# Simple, sequential CSMA sweep: for each row in combinations.csv, run one
# ordinary FIT IoT-LAB experiment via tools/run_fitiot.sh (it submits its own
# reservation, waits for it, collects traffic, downloads OML — same as your
# other single-experiment scripts), analyze it, append the row to the
# dataset, delete that combo's OML files, move on to the next row.
#
# No reservation scheduling — each combo is its own independent experiment,
# one after another. Because each one re-submits from scratch, there's a
# small window between one experiment ending and the next starting where
# another testbed user could grab the nodes first; if a submission fails for
# that reason it's retried a few times with a short pause (see MAX_RETRIES /
# RETRY_WAIT_SEC below) before giving up on that one combo and moving to the
# next — a single failed combo doesn't stop the sweep.
#
# Usage:
#   ./what-if/run_sweep.sh [options]
#
# Options:
#   -u  username                 (default: mihoub)
#   -s  site                     (default: grenoble)
#   -r  receiver node ID         (default: 2)
#   -n  sender node IDs          (default: 3+4+5)
#   -c  combinations CSV         (default: what-if/combinations.csv)
#   -o  output dataset CSV       (default: what-if/dataset.csv)
#   -d  duration minutes per combo (default: 10)
#   -F  firmware dir on IoT-LAB  (default: ~/iot-lab/parts/contiki/examples/radio-link-quality)
#   -P  packets per burst        (default: 1)
#   -a  first combo id to run, inclusive (default: first row in the CSV)
#   -b  last combo id to run, inclusive  (default: last row in the CSV)
#   -t  topology tag — namespaces results/, the dataset, and the error log
#       (results/<tag>/, dataset_<tag>.csv, sweep_errors_<tag>.log), so
#       multiple node topologies never collide. Omit for the flat layout
#       (results/, dataset.csv).
#
# Resumable: rows already present in the output dataset (by id) are skipped
# automatically, so re-running the same command after a crash/interrupt
# picks up where it left off.
#
# Examples:
#   ./what-if/run_sweep.sh
#   ./what-if/run_sweep.sh -t topoA -r 2 -n 3+4+5 -a 1 -b 100
# =============================================================================

set -uo pipefail

# ---------- Defaults --------------------------------------------------------
USER_LOGIN="mihoub"
SITE="grenoble"
RECEIVER_NODE="2"
SENDER_NODES="3+4+5"
COMBOS_CSV=""
OUTPUT_DATASET=""
ROUND_MIN=10
FIRMWARE_FITIOT="~/iot-lab/parts/contiki/examples/radio-link-quality"
NB_PACKETS=1
START_ID=""
END_ID=""
TOPOLOGY=""
MAX_RETRIES=3
RETRY_WAIT_SEC=60
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- Parse arguments -------------------------------------------------
while getopts "u:s:r:n:c:o:d:F:P:a:b:t:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        s) SITE=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        n) SENDER_NODES=$OPTARG ;;
        c) COMBOS_CSV=$OPTARG ;;
        o) OUTPUT_DATASET=$OPTARG ;;
        d) ROUND_MIN=$OPTARG ;;
        F) FIRMWARE_FITIOT=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        a) START_ID=$OPTARG ;;
        b) END_ID=$OPTARG ;;
        t) TOPOLOGY=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

: "${COMBOS_CSV:=$SCRIPT_DIR/combinations.csv}"
if [ -n "$TOPOLOGY" ]; then
    RESULTS_BASE="$SCRIPT_DIR/results/$TOPOLOGY"
    : "${OUTPUT_DATASET:=$SCRIPT_DIR/dataset_${TOPOLOGY}.csv}"
    ERROR_LOG="$SCRIPT_DIR/sweep_errors_${TOPOLOGY}.log"
else
    RESULTS_BASE="$SCRIPT_DIR/results"
    : "${OUTPUT_DATASET:=$SCRIPT_DIR/dataset.csv}"
    ERROR_LOG="$SCRIPT_DIR/sweep_errors.log"
fi

NB_SENDERS=$(echo "$SENDER_NODES" | tr '+' '\n' | wc -l)
mkdir -p "$RESULTS_BASE"

if [ ! -f "$COMBOS_CSV" ]; then
    echo "✗ Combinations file not found: $COMBOS_CSV"
    exit 1
fi

# ---------- Load combos, apply id range + resume filters -------------------
mapfile -t ALL_LINES < <(tail -n +2 "$COMBOS_CSV")

declare -a RUN_IDS RUN_MINBE RUN_MAXBE RUN_MAXBACKOFF RUN_MAXRETRIES
declare -A DONE_IDS
if [ -f "$OUTPUT_DATASET" ]; then
    while IFS=',' read -r did _rest; do
        DONE_IDS["$did"]=1
    done < <(tail -n +2 "$OUTPUT_DATASET" 2>/dev/null)
fi

for line in "${ALL_LINES[@]}"; do
    [ -z "$line" ] && continue
    IFS=',' read -r cid cminbe cmaxbe cmaxbackoff cmaxretries <<< "$line"
    if [ -n "$START_ID" ] && [ "$cid" -lt "$START_ID" ]; then continue; fi
    if [ -n "$END_ID" ] && [ "$cid" -gt "$END_ID" ]; then continue; fi
    if [ -n "${DONE_IDS[$cid]:-}" ]; then continue; fi
    RUN_IDS+=("$cid")
    RUN_MINBE+=("$cminbe")
    RUN_MAXBE+=("$cmaxbe")
    RUN_MAXBACKOFF+=("$cmaxbackoff")
    RUN_MAXRETRIES+=("$cmaxretries")
done

NUM_ROUNDS=${#RUN_IDS[@]}
if [ "$NUM_ROUNDS" -eq 0 ]; then
    echo "Nothing to do — all requested combos are already in $OUTPUT_DATASET"
    exit 0
fi

echo "=============================================="
echo " What-If CSMA Sweep (simple, sequential)"
echo "=============================================="
[ -n "$TOPOLOGY" ] && echo " Topology tag  : $TOPOLOGY"
echo " Combos to run : $NUM_ROUNDS (of ${#ALL_LINES[@]} total in $COMBOS_CSV)"
echo " Duration/combo: ${ROUND_MIN} min"
echo " Receiver      : m3-$RECEIVER_NODE   Senders: m3-$(echo $SENDER_NODES | tr '+' ',')"
echo " Results dir   : $RESULTS_BASE"
echo " Dataset out   : $OUTPUT_DATASET"
echo "=============================================="

# ---------- The 100 (or however many) run lines, one per combo -------------
for idx in "${!RUN_IDS[@]}"; do
    CID=${RUN_IDS[$idx]}
    B=${RUN_MINBE[$idx]}; E=${RUN_MAXBE[$idx]}; K=${RUN_MAXBACKOFF[$idx]}; R=${RUN_MAXRETRIES[$idx]}
    ROUND_DIR="$RESULTS_BASE/id_${CID}"
    mkdir -p "$ROUND_DIR"
    ROUND_NUM=$((idx + 1))

    echo ""
    echo "[$ROUND_NUM/$NUM_ROUNDS] id=$CID  B=$B E=$E K=$K R=$R"

    ATTEMPT=1
    RUN_OK=0
    while [ "$ATTEMPT" -le "$MAX_RETRIES" ]; do
        bash "$REPO_DIR/tools/run_fitiot.sh" \
            -u "$USER_LOGIN" -n "$SENDER_NODES" -r "$RECEIVER_NODE" \
            -d "$ROUND_MIN" -s "$SITE" -o "$ROUND_DIR" \
            -F "$FIRMWARE_FITIOT" -P "$NB_PACKETS" \
            -B "$B" -E "$E" -K "$K" -R "$R"
        if [ $? -eq 0 ] && [ -s "$ROUND_DIR/serial.log" ]; then
            RUN_OK=1
            break
        fi
        echo "  ✗ attempt $ATTEMPT/$MAX_RETRIES failed for id=$CID" | tee -a "$ERROR_LOG"
        ATTEMPT=$((ATTEMPT + 1))
        if [ "$ATTEMPT" -le "$MAX_RETRIES" ]; then
            echo "    retrying in ${RETRY_WAIT_SEC}s..."
            sleep "$RETRY_WAIT_SEC"
        fi
    done

    if [ "$RUN_OK" -ne 1 ]; then
        echo "  ✗ giving up on id=$CID after $MAX_RETRIES attempts — skipping" | tee -a "$ERROR_LOG"
        continue
    fi

    python3 "$REPO_DIR/tools/run_analysis.py" \
        --dir "$ROUND_DIR" --nodes "$NB_SENDERS" --oml-dir "$ROUND_DIR" > "$ROUND_DIR/analysis.log" 2>&1
    if [ $? -ne 0 ] || [ ! -f "$ROUND_DIR/metrics.csv" ]; then
        echo "  ✗ analysis failed — skipping id=$CID (see $ROUND_DIR/analysis.log)" | tee -a "$ERROR_LOG"
        rm -f "$ROUND_DIR"/m3_*.oml
        continue
    fi

    python3 "$REPO_DIR/tools/append_whatif_row.py" \
        --dataset "$OUTPUT_DATASET" \
        --id "$CID" --min-be "$B" --max-be "$E" --max-backoff "$K" --max-frame-retries "$R" \
        --metrics "$ROUND_DIR/metrics.csv"

    # Delete this combo's OML files now that they've been used (metrics.csv
    # already has whatever it needed from them) — the whole point of doing
    # this per-combo instead of at the end is keeping disk usage flat across
    # all 100 runs instead of accumulating all of them.
    rm -f "$ROUND_DIR"/m3_*.oml

    echo "  ✓ id=$CID done"
done

echo ""
echo "=============================================="
echo " Sweep finished."
echo " Dataset : $OUTPUT_DATASET"
[ -f "$ERROR_LOG" ] && echo " Errors  : $ERROR_LOG"
echo "=============================================="
