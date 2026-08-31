#!/bin/bash
# =============================================================================
# what-if/run_campaign.sh
# Sweeps CSMA MAC configurations from what-if/combinations.csv on FIT IoT-LAB
# using a ROLLING CHAIN of scheduled reservations — never more than 2 held at
# once (the IoT-LAB charter caps advance reservations at 2: "it kills down
# resource usage" — see https://www.iot-lab.info/legacy/charter/index.html).
#
# Why not one long reservation: that was the original design, but it ties up
# the nodes for the whole multi-hour sweep even during compile/reflash gaps.
# Why not just submitting each combo's experiment when the previous one ends
# (ASAP mode): that reopens a window between one experiment's Terminated and
# the next's Running where another user could grab the nodes — the same risk
# run_interference_experiment.sh already avoids for a different reason.
#
# The chain, instead:
#   1. Round 0 is submitted ASAP (no reservation time).
#   2. The instant round i reaches Running, round i+1's firmware is compiled
#      and its experiment is submitted with `-r <epoch>` pinned to exactly
#      when round i's slot ends — this SUBMISSION is what claims the slot
#      (IoT-LAB rejects a submission if the nodes aren't free at that time),
#      so as long as it happens before round i's slot ends, no one else can
#      take it. At any instant we hold at most 2 reservations: round i
#      (running) + round i+1 (scheduled) — compliant with the charter.
#   3. Each round gets its own experiment id, so its OML radio file is
#      naturally isolated to that round — no cross-round data to segment,
#      unlike the single-reservation design.
#
# Firmware for each round is built under a unique name (sender_id<N>.iotlab-m3
# / receiver_id<N>.iotlab-m3), mirroring the senderInterferer1/2 pattern in
# run_interference_experiment.sh, and cleaned up right after that round's
# experiment terminates (the frontend has a 2GB quota).
#
# Resumable: rows already present in the output dataset (by id) are skipped,
# so a broken chain (see error log) can be continued by re-running the same
# command — it picks up at the first not-yet-done id.
#
# Usage:
#   ./what-if/run_campaign.sh [options]
#
# Options:
#   -u  username                 (default: mihoub)
#   -s  site                     (default: grenoble)
#   -r  receiver node ID         (default: 2)
#   -n  sender node IDs          (default: 3+4+5)
#   -c  combinations CSV         (default: what-if/combinations.csv)
#   -o  output dataset CSV       (default: what-if/dataset.csv)
#   -d  round (traffic capture) duration minutes (default: 10)
#   -m  boot buffer minutes added on top of -d for each round's OAR reservation
#       (default: 5 — a starting guess only; IoT-LAB pads deploy-type
#       experiments with extra setup/flashing overhead beyond what -d asks
#       for, and the actual amount isn't knowable in advance. The script
#       learns the real value from OAR's own rejection messages after the
#       first mismatch and self-corrects for the rest of the chain, so this
#       just controls how much the very first handoff might waste.)
#   -g  gap seconds between chained reservations, guards against clock skew (default: 5)
#   -F  firmware dir on IoT-LAB  (default: ~/iot-lab/parts/contiki/examples/radio-link-quality)
#   -P  packets per burst        (default: 1)
#   -a  first combo id to run, inclusive (default: first row in the CSV)
#   -b  last combo id to run, inclusive  (default: last row in the CSV)
#   -t  topology tag — namespaces results/, the dataset, and the error log so
#       multiple node topologies never collide (see below)
#
# Multiple topologies: pass a distinct -t per topology (its node set is still
# given via -r/-n). This changes the defaults to:
#   results dir     -> what-if/results/<tag>/id_<combo id>/
#   output dataset  -> what-if/dataset_<tag>.csv   (unless -o overrides it)
#   error log       -> what-if/campaign_errors_<tag>.log
# Without -t, everything falls back to the original flat layout
# (what-if/results/, what-if/dataset.csv) for single-topology use.
#
# Examples:
#   ./what-if/run_campaign.sh -a 1 -b 30
#   ./what-if/run_campaign.sh -a 31 -b 60
#   ./what-if/run_campaign.sh -t topoA -r 2 -n 3+4+5   -a 1 -b 100
#   ./what-if/run_campaign.sh -t topoB -r 20 -n 21+22+23 -a 1 -b 100
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
BOOT_BUFFER_MIN=5
GAP_SEC=5
FIRMWARE_FITIOT="~/iot-lab/parts/contiki/examples/radio-link-quality"
ARM_GCC="/opt/gcc-arm-none-eabi-9-2020-q2-update/bin"
PROFILE_NAME="rssi_11_monitor"
NB_PACKETS=1
START_ID=""
END_ID=""
TOPOLOGY=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- Parse arguments -------------------------------------------------
while getopts "u:s:r:n:c:o:d:m:g:F:P:a:b:t:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        s) SITE=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        n) SENDER_NODES=$OPTARG ;;
        c) COMBOS_CSV=$OPTARG ;;
        o) OUTPUT_DATASET=$OPTARG ;;
        d) ROUND_MIN=$OPTARG ;;
        m) BOOT_BUFFER_MIN=$OPTARG ;;
        g) GAP_SEC=$OPTARG ;;
        F) FIRMWARE_FITIOT=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        a) START_ID=$OPTARG ;;
        b) END_ID=$OPTARG ;;
        t) TOPOLOGY=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

# Defaults are resolved AFTER parsing (not before) so they can depend on -t —
# a topology tag namespaces results/dataset/error-log so concurrent or
# sequential campaigns for different node sets never collide or corrupt each
# other's resume-skip logic.
: "${COMBOS_CSV:=$SCRIPT_DIR/combinations.csv}"
if [ -n "$TOPOLOGY" ]; then
    RESULTS_BASE="$SCRIPT_DIR/results/$TOPOLOGY"
    : "${OUTPUT_DATASET:=$SCRIPT_DIR/dataset_${TOPOLOGY}.csv}"
    ERROR_LOG="$SCRIPT_DIR/campaign_errors_${TOPOLOGY}.log"
else
    RESULTS_BASE="$SCRIPT_DIR/results"
    : "${OUTPUT_DATASET:=$SCRIPT_DIR/dataset.csv}"
    ERROR_LOG="$SCRIPT_DIR/campaign_errors.log"
fi

SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
NB_SENDERS=$(echo "$SENDER_NODES" | tr '+' '\n' | wc -l)
ROUND_OAR_MIN=$(( ROUND_MIN + BOOT_BUFFER_MIN ))
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
echo " What-If CSMA Campaign (rolling reservation chain)"
echo "=============================================="
[ -n "$TOPOLOGY" ] && echo " Topology tag    : $TOPOLOGY"
echo " Combos to run   : $NUM_ROUNDS (of ${#ALL_LINES[@]} total in $COMBOS_CSV)"
echo " Round capture   : ${ROUND_MIN} min   OAR reservation/round: ${ROUND_OAR_MIN} min   Gap: ${GAP_SEC}s"
echo " Receiver        : m3-$RECEIVER_NODE   Senders: m3-$(echo $SENDER_NODES | tr '+' ',')"
echo " Results dir     : $RESULTS_BASE"
echo " Dataset out     : $OUTPUT_DATASET"
echo " Note: at most 2 reservations are ever held at once (current + next),"
echo "       per IoT-LAB's advance-reservation policy."
echo "=============================================="

# ---------- Best-effort cleanup on interrupt --------------------------------
# Only the pipelined "next" reservation is stopped on interrupt (freeing that
# slot for others) — the currently running round is left to finish/expire on
# its own; it was already reserved and its data collection may be mid-flight.
PENDING_NEXT_EXP_ID=""
cleanup() {
    if [ -n "$PENDING_NEXT_EXP_ID" ]; then
        echo ""
        echo "→ Releasing pending reservation id=$PENDING_NEXT_EXP_ID..."
        ssh -o LogLevel=ERROR "$SSH_HOST" "iotlab-experiment stop --id $PENDING_NEXT_EXP_ID" > /dev/null 2>&1
    fi
}
trap cleanup EXIT INT TERM

# =============================================================================
# STEP 1 — Ensure radio monitoring profile exists
# =============================================================================
echo ""
echo "[1/3] Ensuring radio monitoring profile '$PROFILE_NAME' exists..."
ssh -o LogLevel=ERROR "$SSH_HOST" "
    iotlab-profile get -n $PROFILE_NAME > /dev/null 2>&1 || \
    iotlab-profile addm3 -n $PROFILE_NAME -rssi -channels 11 -rperiod 1
"
if [ $? -ne 0 ]; then
    echo "  ✗ Failed to create radio monitoring profile — aborting"
    exit 1
fi
echo "  ✓ Profile ready"

# =============================================================================
# Helpers
# =============================================================================

# Builds sender_id<N>.iotlab-m3 / receiver_id<N>.iotlab-m3 with the given
# CSMA macros. `make clean` is required every round: CSMA_CONF_* is consumed
# by shared stack objects (csma.o etc.), not just the top-level example file,
# so without a clean, a stale object built with a previous round's macros can
# get silently relinked into this round's binary.
compile_round() {
    local cid=$1 b=$2 e=$3 k=$4 r=$5
    ssh -o LogLevel=ERROR "$SSH_HOST" "
        export PATH=${ARM_GCC}:\$PATH &&
        cd $FIRMWARE_FITIOT &&
        make clean 2>&1 &&
        cp sender.c sender_id${cid}.c &&
        cp receiver.c receiver_id${cid}.c &&
        make TARGET=iotlab-m3 NB_PACKETS=${NB_PACKETS} \
            CSMA_MIN_BE=${b} CSMA_MAX_BE=${e} \
            CSMA_MAX_BACKOFF=${k} CSMA_MAX_FRAME_RETRIES=${r} \
            sender_id${cid}.iotlab-m3 receiver_id${cid}.iotlab-m3 2>&1
    "
}

# Submits round $cid's experiment. If $start_epoch is empty, submits ASAP;
# otherwise pins it with -r (this is the call that actually claims the slot).
# Sets globals $LAST_SUBMIT_ID (empty on failure) and $LAST_SUBMIT_ERROR
# (full error text on failure, for extract_suggested_epoch below) — NOT an
# echoed return value, because callers that capture output via $(...) run
# this function in a subshell, and any variable it set would be discarded
# the instant that subshell exits (bash gotcha: subshells can read the
# parent's variables but writes never propagate back). Call this as a plain
# statement, then read $LAST_SUBMIT_ID / $LAST_SUBMIT_ERROR afterward.
#
# IoT-LAB pads deploy-type experiments with node setup/flashing overhead
# beyond the requested -d, so the OAR walltime actually reserved is longer
# than ROUND_OAR_MIN; rather than guess that padding, we let OAR's own
# rejection message ("this reservation could run at <time>") tell us the
# true earliest valid slot.
LAST_SUBMIT_ID=""
LAST_SUBMIT_ERROR=""
submit_round() {
    local cid=$1 start_epoch=$2
    local exp_name="whatif_id${cid}_$(date +%s)"
    local submit_cmd="iotlab-experiment submit -n $exp_name -d $ROUND_OAR_MIN"
    [ -n "$start_epoch" ] && submit_cmd="$submit_cmd -r $start_epoch"
    for NODE in $(echo "$SENDER_NODES" | tr '+' ' '); do
        submit_cmd="$submit_cmd -l $SITE,m3,$NODE,${FIRMWARE_FITIOT}/sender_id${cid}.iotlab-m3,$PROFILE_NAME"
    done
    submit_cmd="$submit_cmd -l $SITE,m3,$RECEIVER_NODE,${FIRMWARE_FITIOT}/receiver_id${cid}.iotlab-m3"

    local combined
    combined=$(ssh -o LogLevel=ERROR "$SSH_HOST" "$submit_cmd" 2>&1)
    LAST_SUBMIT_ERROR="$combined"
    LAST_SUBMIT_ID=$(echo "$combined" | grep -o '"id": [0-9]*' | grep -o '[0-9]*')
    [ -z "$LAST_SUBMIT_ID" ] && echo "$combined" >> "$ERROR_LOG"
}

# Parses "...this reservation could run at YYYY-MM-DD HH:MM:SS..." out of a
# rejected submission's error text and converts it to an epoch. IoT-LAB sites
# are all in France, so the timestamp is interpreted in Europe/Paris
# regardless of the machine running this script. Echoes nothing if not found.
extract_suggested_epoch() {
    local suggested
    suggested=$(echo "$1" | grep -oE 'could run at [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' \
        | head -1 | sed 's/could run at //')
    [ -z "$suggested" ] && return
    TZ='Europe/Paris' date -d "$suggested" +%s 2>/dev/null
}

cleanup_round_firmware() {
    local cid=$1
    ssh -o LogLevel=ERROR "$SSH_HOST" "
        cd $FIRMWARE_FITIOT &&
        rm -f sender_id${cid}.c receiver_id${cid}.c sender_id${cid}.iotlab-m3 receiver_id${cid}.iotlab-m3
    " > /dev/null 2>&1
}

# =============================================================================
# STEP 2 — Bootstrap: compile + submit round 0 (ASAP, no reservation needed)
# =============================================================================
echo ""
echo "[2/3] Starting the chain — round 0 (id=${RUN_IDS[0]}) submits ASAP..."
COMPILE_OUT=$(compile_round "${RUN_IDS[0]}" "${RUN_MINBE[0]}" "${RUN_MAXBE[0]}" "${RUN_MAXBACKOFF[0]}" "${RUN_MAXRETRIES[0]}")
if [ $? -ne 0 ]; then
    echo "  ✗ Initial compilation failed:" | tee -a "$ERROR_LOG"
    echo "$COMPILE_OUT" | tee -a "$ERROR_LOG"
    exit 1
fi
EXP_ID=$(submit_round "${RUN_IDS[0]}" "")
if [ -z "$EXP_ID" ]; then
    echo "  ✗ Initial submission failed — see $ERROR_LOG"
    exit 1
fi
declare -a EXP_IDS
EXP_IDS[0]=$EXP_ID
echo "  ✓ Submitted — id=$EXP_ID"

POSITIONS_FILE="$RESULTS_BASE/node_positions.json"
ALL_NODES="${RECEIVER_NODE}+${SENDER_NODES}"
python3 "$REPO_DIR/tools/get_fitiot_positions.py" \
    --host "$SSH_HOST" --nodes "$ALL_NODES" --receiver "$RECEIVER_NODE" \
    --output "$POSITIONS_FILE" > /dev/null 2>&1
[ -f "$POSITIONS_FILE" ] && echo "  ✓ Positions saved: $POSITIONS_FILE"

# =============================================================================
# STEP 3 — Roll through the chain
# =============================================================================
echo ""
echo "[3/3] Running $NUM_ROUNDS combo(s)..."

CHAIN_BROKEN=0
LEARNED_PADDING_SEC=0
WAIT_SECONDS=$(( ROUND_MIN * 60 ))

for idx in "${!RUN_IDS[@]}"; do
    CID=${RUN_IDS[$idx]}
    EXP_ID=${EXP_IDS[$idx]:-}
    if [ -z "$EXP_ID" ]; then
        echo ""
        echo "  ✗ No reservation for id=$CID (chain broke earlier) — stopping."
        echo "    Re-run the same command to resume from here." | tee -a "$ERROR_LOG"
        break
    fi
    # This round is now the one actively being driven by the loop itself, so
    # it no longer needs the trap's protection (a Ctrl+C from here on just
    # lets it finish/expire naturally, same as the very first round).
    PENDING_NEXT_EXP_ID=""

    ROUND_DIR="$RESULTS_BASE/id_${CID}"
    mkdir -p "$ROUND_DIR"
    ROUND_NUM=$((idx + 1))

    echo ""
    echo "  [$ROUND_NUM/$NUM_ROUNDS] id=$CID  B=${RUN_MINBE[$idx]} E=${RUN_MAXBE[$idx]} K=${RUN_MAXBACKOFF[$idx]} R=${RUN_MAXRETRIES[$idx]}  (exp id=$EXP_ID)"
    echo "    → waiting for Running..."
    ssh -o LogLevel=ERROR "$SSH_HOST" "iotlab-experiment wait --id $EXP_ID --state Running" > /dev/null 2>&1
    ROUND_START_EPOCH=$(date +%s)
    echo "    ✓ Running"

    # --- pipeline: claim the NEXT slot now, while this round is live ---
    NEXT_IDX=$((idx + 1))
    if [ "$NEXT_IDX" -lt "$NUM_ROUNDS" ] && [ "$CHAIN_BROKEN" -eq 0 ]; then
        NEXT_CID=${RUN_IDS[$NEXT_IDX]}
        echo "    → compiling next round (id=$NEXT_CID) in parallel with this one's traffic..."
        NCOMPILE_OUT=$(compile_round "$NEXT_CID" "${RUN_MINBE[$NEXT_IDX]}" "${RUN_MAXBE[$NEXT_IDX]}" "${RUN_MAXBACKOFF[$NEXT_IDX]}" "${RUN_MAXRETRIES[$NEXT_IDX]}")
        if [ $? -ne 0 ]; then
            echo "    ✗ compile for id=$NEXT_CID failed — chain will stop after this round" | tee -a "$ERROR_LOG"
            echo "$NCOMPILE_OUT" >> "$ERROR_LOG"
            CHAIN_BROKEN=1
        else
            # Rounded up to the next full minute — OAR-based reservations
            # commonly require minute-aligned start times (durations are
            # already minute-granular via -d), so raw epoch seconds risk a
            # rejected submission for no visible reason.
            # LEARNED_PADDING_SEC accounts for setup/flashing overhead IoT-LAB
            # adds on top of the requested -d for deploy-type experiments —
            # ROUND_OAR_MIN alone underestimates the real walltime, so this
            # round's slot ends later than we'd naively compute. It starts at
            # 0 and gets set from OAR's own rejection message below, so later
            # rounds in the chain stop needing a rejected first attempt.
            RAW_NEXT_START=$(( ROUND_START_EPOCH + ROUND_OAR_MIN * 60 + LEARNED_PADDING_SEC + GAP_SEC ))
            NEXT_START=$(( (RAW_NEXT_START + 59) / 60 * 60 ))
            NEXT_EXP_ID=$(submit_round "$NEXT_CID" "$NEXT_START")
            if [ -z "$NEXT_EXP_ID" ]; then
                SUGGESTED_EPOCH=$(extract_suggested_epoch "$LAST_SUBMIT_ERROR")
                if [ -n "$SUGGESTED_EPOCH" ]; then
                    echo "    ⚠ id=$NEXT_CID rejected — OAR needs setup overhead we didn't account for;" | tee -a "$ERROR_LOG"
                    echo "      retrying at OAR's suggested time $(date -d @"$SUGGESTED_EPOCH" '+%H:%M:%S')..." | tee -a "$ERROR_LOG"
                    RETRY_START=$(( SUGGESTED_EPOCH + GAP_SEC ))
                    RETRY_START=$(( (RETRY_START + 59) / 60 * 60 ))
                    LEARNED_ADJUST=$(( SUGGESTED_EPOCH - RAW_NEXT_START ))
                    [ "$LEARNED_ADJUST" -gt "$LEARNED_PADDING_SEC" ] && LEARNED_PADDING_SEC=$LEARNED_ADJUST
                else
                    echo "    ⚠ scheduled reservation for id=$NEXT_CID was rejected (no suggested time found) — retrying once..." | tee -a "$ERROR_LOG"
                    sleep "$GAP_SEC"
                    RAW_RETRY_START=$(( $(date +%s) + GAP_SEC ))
                    RETRY_START=$(( (RAW_RETRY_START + 59) / 60 * 60 ))
                fi
                NEXT_EXP_ID=$(submit_round "$NEXT_CID" "$RETRY_START")
                [ -n "$NEXT_EXP_ID" ] && NEXT_START=$RETRY_START
            fi
            if [ -z "$NEXT_EXP_ID" ]; then
                echo "    ✗ could not reserve id=$NEXT_CID — chain will stop after this round" | tee -a "$ERROR_LOG"
                CHAIN_BROKEN=1
            else
                EXP_IDS[$NEXT_IDX]=$NEXT_EXP_ID
                PENDING_NEXT_EXP_ID=$NEXT_EXP_ID
                echo "    ✓ id=$NEXT_CID reserved (exp id=$NEXT_EXP_ID, starts at $(date -d @"$NEXT_START" '+%H:%M:%S'))"
            fi
        fi
    fi

    sleep 2
    echo "    → collecting for ${ROUND_MIN} min..."
    sleep $((WAIT_SECONDS + 10)) | ssh -o LogLevel=QUIET "$SSH_HOST" \
        "timeout $WAIT_SECONDS serial_aggregator -i $EXP_ID" \
        > "$ROUND_DIR/serial.log" 2>&1

    ssh -o LogLevel=ERROR "$SSH_HOST" "iotlab-experiment wait --id $EXP_ID --state Terminated" > /dev/null 2>&1

    for NODE in $(echo "$SENDER_NODES" | tr '+' ' '); do
        scp -q -o LogLevel=ERROR "${SSH_HOST}:~/.iot-lab/${EXP_ID}/radio/m3_${NODE}.oml" \
            "$ROUND_DIR/m3_${NODE}.oml" 2>/dev/null
    done

    cleanup_round_firmware "$CID"

    if [ ! -s "$ROUND_DIR/serial.log" ]; then
        echo "    ✗ empty serial.log — skipping id=$CID" | tee -a "$ERROR_LOG"
    else
        python3 "$REPO_DIR/tools/run_analysis.py" \
            --dir "$ROUND_DIR" --nodes "$NB_SENDERS" --oml-dir "$ROUND_DIR" > "$ROUND_DIR/analysis.log" 2>&1
        if [ $? -ne 0 ] || [ ! -f "$ROUND_DIR/metrics.csv" ]; then
            echo "    ✗ analysis failed — skipping id=$CID (see $ROUND_DIR/analysis.log)" | tee -a "$ERROR_LOG"
        else
            python3 "$REPO_DIR/tools/append_whatif_row.py" \
                --dataset "$OUTPUT_DATASET" \
                --id "$CID" --min-be "${RUN_MINBE[$idx]}" --max-be "${RUN_MAXBE[$idx]}" \
                --max-backoff "${RUN_MAXBACKOFF[$idx]}" --max-frame-retries "${RUN_MAXRETRIES[$idx]}" \
                --metrics "$ROUND_DIR/metrics.csv"
            echo "    ✓ id=$CID done"
        fi
    fi

    rm -f "$ROUND_DIR"/m3_*.oml

    if [ "$CHAIN_BROKEN" -eq 1 ]; then
        echo ""
        echo "  Chain stopped after id=$CID. Re-run the same command to continue —"
        echo "  already-recorded ids in $OUTPUT_DATASET are skipped automatically."
        break
    fi
done

echo ""
echo "=============================================="
echo " Campaign finished."
echo " Dataset : $OUTPUT_DATASET"
[ -f "$ERROR_LOG" ] && echo " Errors  : $ERROR_LOG (check for skipped/broken-chain combos)"
echo "=============================================="
