#!/bin/bash
# =============================================================================
# run_fitiot.sh
# FIT IoT-LAB runner — mirrors run_exp.sh logic
#
# Called by run_unified.sh with:
#   -u username -n sender_nodes -r receiver_node -d duration -s site -o output_dir -F firmware_dir
#
# MAC (CSMA) parameters -B/-E/-K/-R override csma.c's CSMA_CONF_* macros at
# compile time (see examples/radio-link-quality/Makefile on the FIT IoT-LAB
# frontend). Defaults below match csma.c's own built-in defaults, so omitting
# them reproduces the exact behavior of past experiments.
# =============================================================================

USER_LOGIN="mihoub"
SENDER_NODES="3+4+5"
RECEIVER_NODE="2"
DURATION=5
SITE="grenoble"
OUTPUT_DIR=""
FIRMWARE_DIR="$HOME/iot-lab/parts/contiki/examples/radio-link-quality"
ARM_GCC="/opt/gcc-arm-none-eabi-9-2020-q2-update/bin"
NB_PACKETS=1
PHASE_DURATION_S=900
PROFILE_NAME="rssi_11_monitor"
CSMA_MIN_BE=0
CSMA_MAX_BE=4
CSMA_MAX_BACKOFF=5
CSMA_MAX_FRAME_RETRIES=7

while getopts "u:n:r:d:s:o:F:P:D:B:E:K:R:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        n) SENDER_NODES=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        d) DURATION=$OPTARG ;;
        s) SITE=$OPTARG ;;
        o) OUTPUT_DIR=$OPTARG ;;
        F) FIRMWARE_DIR=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        D) PHASE_DURATION_S=$OPTARG ;;
        B) CSMA_MIN_BE=$OPTARG ;;
        E) CSMA_MAX_BE=$OPTARG ;;
        K) CSMA_MAX_BACKOFF=$OPTARG ;;
        R) CSMA_MAX_FRAME_RETRIES=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
WAIT_SECONDS=$(( DURATION * 60 ))
EXP_NAME="unified_$(date +%Y%m%d_%H%M%S)"

# ---------- Step 0 — Ensure radio monitoring profile exists ----------------

echo "  [FIT] Ensuring radio monitoring profile '$PROFILE_NAME' exists..."
ssh $SSH_HOST "
    iotlab-profile get -n $PROFILE_NAME > /dev/null 2>&1 || \
    iotlab-profile addm3 -n $PROFILE_NAME -rssi -channels 11 -rperiod 1 
"
if [ $? -ne 0 ]; then
    echo "  [FIT] ✗ Failed to create radio monitoring profile '$PROFILE_NAME'"
    exit 1
fi
echo "  [FIT] ✓ Profile '$PROFILE_NAME' ready"

# ---------- Step 1 — Compile firmware --------------------------------------

echo "  [FIT] Compiling firmware..."

COMPILE_LOG=$(ssh $SSH_HOST "
    export PATH=${ARM_GCC}:\$PATH &&
    cd $FIRMWARE_DIR &&
    make clean 2>&1 &&
    make TARGET=iotlab-m3 NB_PACKETS=${NB_PACKETS} PHASE_DURATION_S=${PHASE_DURATION_S} \
        CSMA_MIN_BE=${CSMA_MIN_BE} CSMA_MAX_BE=${CSMA_MAX_BE} \
        CSMA_MAX_BACKOFF=${CSMA_MAX_BACKOFF} CSMA_MAX_FRAME_RETRIES=${CSMA_MAX_FRAME_RETRIES} 2>&1
")
COMPILE_STATUS=$?

if [ $COMPILE_STATUS -ne 0 ]; then
    echo "  [FIT] ✗ Compilation failed — build output:"
    echo "$COMPILE_LOG" | sed 's/^/    /'
    exit 1
fi
echo "  [FIT] ✓ Compiled: sender.iotlab-m3 + receiver.iotlab-m3"
echo "  [FIT]   CSMA config: min_be=${CSMA_MIN_BE} max_be=${CSMA_MAX_BE} max_backoff=${CSMA_MAX_BACKOFF} max_frame_retries=${CSMA_MAX_FRAME_RETRIES}"

# ---------- Step 2 — Submit experiment -------------------------------------

echo "  [FIT] Submitting experiment..."

SUBMIT_CMD="iotlab-experiment submit -n $EXP_NAME -d $DURATION"

for NODE in $(echo $SENDER_NODES | tr '+' ' '); do
    SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$NODE,${FIRMWARE_DIR}/sender.iotlab-m3,$PROFILE_NAME"
done
SUBMIT_CMD="$SUBMIT_CMD -l $SITE,m3,$RECEIVER_NODE,${FIRMWARE_DIR}/receiver.iotlab-m3"

SUBMIT_OUTPUT=$(ssh $SSH_HOST "$SUBMIT_CMD")
EXP_ID=$(echo $SUBMIT_OUTPUT | grep -o '"id": [0-9]*' | grep -o '[0-9]*')

if [ -z "$EXP_ID" ]; then
    echo "  [FIT] ✗ Submission failed: $SUBMIT_OUTPUT"
    exit 1
fi
echo "  [FIT] ✓ Submitted — ID: $EXP_ID"
echo "$EXP_ID" > "$OUTPUT_DIR/experiment_id.txt"

# ---------- Step 3 — Wait for Running + collect logs -----------------------

echo "  [FIT] Waiting for Running state..."
ssh $SSH_HOST "iotlab-experiment wait --id $EXP_ID --state Running" > /dev/null 2>&1
echo "  [FIT] ✓ Running! Giving nodes 2s to fully boot..."
sleep 2

# Collect serial log in foreground — blocks for full duration
echo "  [FIT] Collecting serial log for $DURATION min..."
sleep $((WAIT_SECONDS + 10)) | ssh -o LogLevel=QUIET "$SSH_HOST" "timeout $WAIT_SECONDS serial_aggregator -i $EXP_ID" \
    > "$OUTPUT_DIR/serial.log" 2>&1

echo "  [FIT] ✓ Serial log: $OUTPUT_DIR/serial.log"

# ---------- Step 4 — Download results --------------------------------------

echo "  [FIT] Waiting for experiment to terminate..."
ssh $SSH_HOST "iotlab-experiment wait --id $EXP_ID --state Terminated" > /dev/null 2>&1

# Download per-sender OML (RSSI) files
for NODE in $(echo $SENDER_NODES | tr '+' ' '); do
    scp ${SSH_HOST}:~/.iot-lab/${EXP_ID}/radio/m3_${NODE}.oml \
        "$OUTPUT_DIR/m3_${NODE}.oml" 2>/dev/null
    if [ -f "$OUTPUT_DIR/m3_${NODE}.oml" ]; then
        echo "  [FIT] ✓ OML m3-$NODE: $OUTPUT_DIR/m3_${NODE}.oml"
    fi
done

echo "  [FIT] ✓ Done — results in $OUTPUT_DIR"
