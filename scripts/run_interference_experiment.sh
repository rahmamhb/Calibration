#!/bin/bash
# =============================================================================
# run_interference_experiment.sh
# Studies the effect of interfering nodes on network behaviour on FIT IoT-LAB.
#
# Timeline (stable phase is -b minutes, default 10; the other 3 phases are
# -p minutes each, default 10):
#   Phase 0  STABLE       [0, b)        main senders only
#   Phase 1  INTERFERE-1  [b, b+p)      + interferer group 1 joins
#   Phase 2  INTERFERE-2  [b+p, b+2p)   + interferer group 2 joins (both active)
#   Phase 3  RECOVERY     [b+2p, end)   interferers stopped — back to stable
#
# IMPORTANT — single experiment, not three:
# All nodes (receiver, main senders, both interferer groups) are reserved in
# ONE iotlab-experiment submission at t=0 for the full duration. Submitting
# the interferer groups later (as their own experiments) would leave those
# nodes unreserved in the meantime, so another testbed user could grab them
# before the interference phase starts. Instead, the join/leave timing is
# baked into the interferer firmware itself (contiki-firmware/FitIot-Lab/senderInterferer.c,
# compiled twice with different DELAY_S/ACTIVE_S) — each interferer node's
# own clock decides when to start/stop flooding, the same way
# contiki-firmware/FitIot-Lab/senderTX.c already drives its TX-power phases on-device.
#
# Usage:
#   ./run_interference_experiment.sh [options]
#
# Options:
#   -u  username                 (default: mihoub)
#   -s  site                     (default: grenoble)
#   -r  receiver node ID         (default: 2)
#   -n  main sender node IDs     (default: 3+4+5)
#   -i  interferer group 1 IDs   (default: 10+11)
#   -j  interferer group 2 IDs   (default: 12+13)
#   -b  stable phase duration minutes      (default: same as -p)
#   -p  interference phase duration minutes (default: 10)
#   -d  total duration minutes   (default: stable + 3 * phase duration)
#   -F  firmware dir on IoT-LAB  (default: ~/iot-lab/parts/contiki/examples/radio-link-quality)
#   -P  packets per burst        (default: 1)
# =============================================================================

# ---------- Defaults --------------------------------------------------------
USER_LOGIN="mihoub"
SITE="grenoble"
RECEIVER_NODE="2"
MAIN_SENDERS="3+4+5"
INTERFERER1_NODES="10+11"
INTERFERER2_NODES="12+13"
PHASE_MIN=10
STABLE_MIN=""
TOTAL_DURATION=""
FIRMWARE_FITIOT="~/iot-lab/parts/contiki/examples/radio-link-quality"
ARM_GCC="/opt/gcc-arm-none-eabi-9-2020-q2-update/bin"
PROFILE_NAME="rssi_11_monitor"
NB_PACKETS=1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- Parse arguments -------------------------------------------------
while getopts "u:s:r:n:i:j:b:p:d:F:P:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        s) SITE=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        n) MAIN_SENDERS=$OPTARG ;;
        i) INTERFERER1_NODES=$OPTARG ;;
        j) INTERFERER2_NODES=$OPTARG ;;
        b) STABLE_MIN=$OPTARG ;;
        p) PHASE_MIN=$OPTARG ;;
        d) TOTAL_DURATION=$OPTARG ;;
        F) FIRMWARE_FITIOT=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

: "${STABLE_MIN:=$PHASE_MIN}"
: "${TOTAL_DURATION:=$(( STABLE_MIN + PHASE_MIN * 3 ))}"

if [ "$TOTAL_DURATION" -lt $(( STABLE_MIN + PHASE_MIN * 2 )) ]; then
    echo "✗ Total duration ($TOTAL_DURATION min) must be at least stable + 2 × interference phase duration ($((STABLE_MIN + PHASE_MIN*2)) min)"
    exit 1
fi

# ---------- Derived values --------------------------------------------------
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
EXP_NAME="interference_${TIMESTAMP}"
RESULTS_BASE="$REPO_DIR/results/$EXP_NAME"
OUTPUT_DIR="$RESULTS_BASE/main"
SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
ALL_NODES="${RECEIVER_NODE}+${MAIN_SENDERS}+${INTERFERER1_NODES}+${INTERFERER2_NODES}"
NB_MAIN_SENDERS=$(echo $MAIN_SENDERS | tr '+' '\n' | wc -l)
WAIT_SECONDS=$(( TOTAL_DURATION * 60 ))

# Join/leave windows (seconds) baked into each interferer binary
INTF1_DELAY_S=$(( STABLE_MIN * 60 ))                  # joins at start of Phase 1
INTF1_ACTIVE_S=$(( PHASE_MIN * 2 * 60 ))              # stays through Phase 1 + Phase 2
INTF2_DELAY_S=$(( (STABLE_MIN + PHASE_MIN) * 60 ))    # joins at start of Phase 2
INTF2_ACTIVE_S=$(( PHASE_MIN * 60 ))                  # stays through Phase 2 only

mkdir -p "$OUTPUT_DIR"

echo "=============================================="
echo " Interfering-Node Experiment (single submission)"
echo "=============================================="
echo " Receiver     : m3-$RECEIVER_NODE"
echo " Main senders : m3-$(echo $MAIN_SENDERS | tr '+' ',')"
echo " Interferer 1 : m3-$(echo $INTERFERER1_NODES | tr '+' ',')  (join t=${STABLE_MIN}min, leave t=$((STABLE_MIN+PHASE_MIN*2))min)"
echo " Interferer 2 : m3-$(echo $INTERFERER2_NODES | tr '+' ',')  (join t=$((STABLE_MIN+PHASE_MIN))min, leave t=$((STABLE_MIN+PHASE_MIN*2))min)"
echo " Stable phase : ${STABLE_MIN} min   Interference phase : ${PHASE_MIN} min   Total duration: ${TOTAL_DURATION} min"
echo " Results      : $RESULTS_BASE"
echo "=============================================="

# =============================================================================
# STEP 0 — Fetch positions of all involved nodes (for record-keeping)
# =============================================================================
echo ""
echo "[0/6] Fetching node positions..."
POSITIONS_FILE="$RESULTS_BASE/node_positions.json"
python3 "$REPO_DIR/tools/get_fitiot_positions.py" \
    --host "$SSH_HOST" \
    --nodes "$ALL_NODES" \
    --receiver "$RECEIVER_NODE" \
    --output "$POSITIONS_FILE"
[ -f "$POSITIONS_FILE" ] && echo "  ✓ Positions saved: $POSITIONS_FILE" || echo "  ⚠ Failed to fetch positions — continuing anyway"

# =============================================================================
# STEP 1 — Ensure radio monitoring profile exists
# =============================================================================
echo ""
echo "[1/6] Ensuring radio monitoring profile '$PROFILE_NAME' exists..."
ssh -o LogLevel=ERROR $SSH_HOST "
    iotlab-profile get -n $PROFILE_NAME > /dev/null 2>&1 || \
    iotlab-profile addm3 -n $PROFILE_NAME -rssi -channels 11 -rperiod 1
"
if [ $? -ne 0 ]; then
    echo "  ✗ Failed to create radio monitoring profile — aborting"
    exit 1
fi
echo "  ✓ Profile '$PROFILE_NAME' ready"

# =============================================================================
# STEP 2 — Compile firmware
#   sender.iotlab-m3 / receiver.iotlab-m3 : main pair (unchanged firmware)
#   senderInterferer{1,2}.iotlab-m3       : same source, two compiles with
#                                            different DELAY_S/ACTIVE_S, so
#                                            both binaries can coexist on disk
#                                            for the single submit below.
# =============================================================================
echo ""
echo "[2/6] Compiling firmware..."

echo "  → main pair (NB_PACKETS=$NB_PACKETS)..."
COMPILE_LOG=$(ssh -o LogLevel=ERROR $SSH_HOST "
    export PATH=${ARM_GCC}:\$PATH &&
    cd $FIRMWARE_FITIOT &&
    make clean 2>&1 &&
    make TARGET=iotlab-m3 NB_PACKETS=${NB_PACKETS} sender.iotlab-m3 receiver.iotlab-m3 2>&1
")
if [ $? -ne 0 ]; then
    echo "  ✗ Main firmware compilation failed — build output:"
    echo "$COMPILE_LOG" | sed 's/^/    /'
    exit 1
fi
echo "  ✓ sender.iotlab-m3 + receiver.iotlab-m3"

echo "  → uploading interferer source ($REPO_DIR/contiki-firmware/FitIot-Lab/senderInterferer.c)..."
scp -q -o LogLevel=ERROR "$REPO_DIR/contiki-firmware/FitIot-Lab/senderInterferer.c" "${SSH_HOST}:${FIRMWARE_FITIOT}/senderInterferer.c"
if [ $? -ne 0 ]; then
    echo "  ✗ Failed to upload senderInterferer.c — aborting"
    exit 1
fi

echo "  → interferer 1 (delay=${INTF1_DELAY_S}s active=${INTF1_ACTIVE_S}s)..."
COMPILE_LOG=$(ssh -o LogLevel=ERROR $SSH_HOST "
    export PATH=${ARM_GCC}:\$PATH &&
    cd $FIRMWARE_FITIOT &&
    cp senderInterferer.c senderInterferer1.c &&
    make TARGET=iotlab-m3 NB_PACKETS=${NB_PACKETS} DEFINES=DELAY_S=${INTF1_DELAY_S},ACTIVE_S=${INTF1_ACTIVE_S} senderInterferer1.iotlab-m3 2>&1
")
if [ $? -ne 0 ]; then
    echo "  ✗ Interferer 1 compilation failed — build output:"
    echo "$COMPILE_LOG" | sed 's/^/    /'
    exit 1
fi
echo "  ✓ senderInterferer1.iotlab-m3"

echo "  → interferer 2 (delay=${INTF2_DELAY_S}s active=${INTF2_ACTIVE_S}s)..."
COMPILE_LOG=$(ssh -o LogLevel=ERROR $SSH_HOST "
    export PATH=${ARM_GCC}:\$PATH &&
    cd $FIRMWARE_FITIOT &&
    cp senderInterferer.c senderInterferer2.c &&
    make TARGET=iotlab-m3 NB_PACKETS=${NB_PACKETS} DEFINES=DELAY_S=${INTF2_DELAY_S},ACTIVE_S=${INTF2_ACTIVE_S} senderInterferer2.iotlab-m3 2>&1
")
if [ $? -ne 0 ]; then
    echo "  ✗ Interferer 2 compilation failed — build output:"
    echo "$COMPILE_LOG" | sed 's/^/    /'
    exit 1
fi
echo "  ✓ senderInterferer2.iotlab-m3"

# =============================================================================
# STEP 3 — Submit ONE experiment with all four node groups
# =============================================================================
echo ""
echo "[3/6] Submitting single experiment (all nodes reserved for ${TOTAL_DURATION} min)..."

SUBMIT_CMD="iotlab-experiment submit -n $EXP_NAME -d $TOTAL_DURATION"

for NODE in $(echo $MAIN_SENDERS | tr '+' ' '); do
    SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$NODE,${FIRMWARE_FITIOT}/sender.iotlab-m3,$PROFILE_NAME"
done
for NODE in $(echo $INTERFERER1_NODES | tr '+' ' '); do
    SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$NODE,${FIRMWARE_FITIOT}/senderInterferer1.iotlab-m3,$PROFILE_NAME"
done
for NODE in $(echo $INTERFERER2_NODES | tr '+' ' '); do
    SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$NODE,${FIRMWARE_FITIOT}/senderInterferer2.iotlab-m3,$PROFILE_NAME"
done
SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$RECEIVER_NODE,${FIRMWARE_FITIOT}/receiver.iotlab-m3"

SUBMIT_OUTPUT=$(ssh -o LogLevel=ERROR $SSH_HOST "$SUBMIT_CMD")
EXP_ID=$(echo $SUBMIT_OUTPUT | grep -o '"id": [0-9]*' | grep -o '[0-9]*')

if [ -z "$EXP_ID" ]; then
    echo "  ✗ Submission failed: $SUBMIT_OUTPUT"
    exit 1
fi
echo "  ✓ Submitted — ID: $EXP_ID"
echo "$EXP_ID" > "$OUTPUT_DIR/experiment_id.txt"

# =============================================================================
# STEP 4 — Wait for Running, then collect the combined serial log
# =============================================================================
echo ""
echo "[4/6] Waiting for Running state..."
ssh $SSH_HOST "iotlab-experiment wait --id $EXP_ID --state Running" > /dev/null 2>&1
echo "  ✓ Running — all nodes booted, interferer timers start counting now"
sleep 2

echo "  → Collecting serial log for $TOTAL_DURATION min..."
sleep $((WAIT_SECONDS + 10)) | ssh -o LogLevel=QUIET "$SSH_HOST" "timeout $WAIT_SECONDS serial_aggregator -i $EXP_ID" \
    > "$OUTPUT_DIR/serial.log" 2>&1
echo "  ✓ Serial log: $OUTPUT_DIR/serial.log"

# =============================================================================
# STEP 5 — Download per-node OML (RSSI) files
# =============================================================================
echo ""
echo "[5/6] Waiting for termination and downloading OML files..."
ssh $SSH_HOST "iotlab-experiment wait --id $EXP_ID --state Terminated" > /dev/null 2>&1

for NODE in $(echo $MAIN_SENDERS | tr '+' ' ') $(echo $INTERFERER1_NODES | tr '+' ' ') $(echo $INTERFERER2_NODES | tr '+' ' '); do
    scp -q ${SSH_HOST}:~/.iot-lab/${EXP_ID}/radio/m3_${NODE}.oml \
        "$OUTPUT_DIR/m3_${NODE}.oml" 2>/dev/null
done
echo "  ✓ Done"

# =============================================================================
# STEP 6 — Analysis and plots on the combined log
# =============================================================================
echo ""
echo "[6/6] Computing metrics..."

if [ -f "$OUTPUT_DIR/serial.log" ]; then
    python3 "$REPO_DIR/tools/run_analysis.py" \
        --dir     "$OUTPUT_DIR" \
        --nodes   "$NB_MAIN_SENDERS" \
        --oml-dir "$OUTPUT_DIR"

    python3 "$REPO_DIR/tools/plot_single.py" \
        --dir        "$OUTPUT_DIR" \
        --label      "Main (with interference)" \
        --output-dir "$RESULTS_BASE"

    echo "  → Per-phase time evolution (window = ${PHASE_MIN} min, matches the 4 phases)..."
    python3 "$REPO_DIR/tools/plot_time_evolution.py" \
        --log     "$OUTPUT_DIR/serial.log" \
        --window  "$(( PHASE_MIN * 60 ))" \
        --nodes   "$NB_MAIN_SENDERS" \
        --oml-dir "$OUTPUT_DIR" \
        --output  "$RESULTS_BASE/phase_time_evolution.png"
else
    echo "  ⚠ $OUTPUT_DIR/serial.log not found — skipping analysis"
fi

# =============================================================================
# Experiment summary
# =============================================================================
cat > "$RESULTS_BASE/experiment_info.txt" << EXPEOF
Experiment          : $EXP_NAME
Experiment ID       : $EXP_ID
Date                : $(date)
Site                : $SITE
Receiver            : m3-$RECEIVER_NODE
Main senders        : m3-$(echo $MAIN_SENDERS | tr '+' ',')
Interferer group 1  : m3-$(echo $INTERFERER1_NODES | tr '+' ',')
Interferer group 2  : m3-$(echo $INTERFERER2_NODES | tr '+' ',')
Stable phase duration      : ${STABLE_MIN} min
Interference phase duration : ${PHASE_MIN} min
Total duration      : ${TOTAL_DURATION} min
Phases (on-device timers, see contiki-firmware/FitIot-Lab/senderInterferer.c):
  Phase 0  STABLE       [0, ${STABLE_MIN})min                              main senders only
  Phase 1  INTERFERE-1  [${STABLE_MIN}, $((STABLE_MIN+PHASE_MIN)))min                        + interferer group 1
  Phase 2  INTERFERE-2  [$((STABLE_MIN+PHASE_MIN)), $((STABLE_MIN+PHASE_MIN*2)))min                        + interferer group 2 (both active)
  Phase 3  RECOVERY     [$((STABLE_MIN+PHASE_MIN*2)), ${TOTAL_DURATION})min   interferers stopped — back to stable
EXPEOF

echo ""
echo "=============================================="
echo " INTERFERENCE EXPERIMENT DONE"
echo "=============================================="
echo " Results : $RESULTS_BASE"
echo " Log     : $OUTPUT_DIR/serial.log"
echo " Metrics : $OUTPUT_DIR/metrics.csv"
echo " Plots   : $RESULTS_BASE/*.png"
echo " Summary : $RESULTS_BASE/experiment_info.txt"
echo "=============================================="
