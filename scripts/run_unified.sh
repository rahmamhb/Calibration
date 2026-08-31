#!/bin/bash
# =============================================================================
# run_unified.sh
# Runs FIT IoT-LAB + Cooja experiments in parallel, then compares metrics
#
# Usage:
#   ./run_unified.sh [options]
#
# Options:
#   -u  username                (default: mihoub)
#   -n  sender node IDs         (default: 3+4+5)
#   -r  receiver node ID        (default: 2)
#   -d  duration minutes        (default: 5)
#   -s  site                    (default: grenoble)
#   -C  cooja path              (default: ~/cooja)
#   -F  FIT IoT-LAB firmware dir (default: ~/iot-lab/parts/contiki/examples/radio-link-quality)
#   -K  Cooja firmware dir       (default: ~/contiki-ng/examples/radio-link-quality)
#   -P  packets per burst        (default: 1)
#   -B  CSMA_MIN_BE              (default: 0)
#   -E  CSMA_MAX_BE              (default: 4)
#   -X  CSMA_MAX_BACKOFF         (default: 5)   [-K is taken by Cooja firmware dir]
#   -R  CSMA_MAX_FRAME_RETRIES   (default: 7)
#
# CSMA params are applied identically on both sides: Cooja via
# examples/radio-link-quality/Makefile's CSMA_CONF_* overrides, FIT IoT-LAB
# via the same mechanism on the remote frontend (see tools/run_fitiot.sh).
# =============================================================================

# ---------- Defaults --------------------------------------------------------
USER_LOGIN="mihoub"
SENDER_NODES="3+4+5"
RECEIVER_NODE="2"
DURATION=5
SITE="grenoble"
COOJA_PATH="$HOME/contiki-ng/tools/cooja/"
FIRMWARE_FITIOT="~/iot-lab/parts/contiki/examples/radio-link-quality"  # path on IoT-LAB server
FIRMWARE_COOJA="$HOME/contiki-ng/examples/radio-link-quality"
NB_PACKETS=1
CSMA_MIN_BE=0
CSMA_MAX_BE=4
CSMA_MAX_BACKOFF=5
CSMA_MAX_FRAME_RETRIES=7
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- Parse arguments -------------------------------------------------
while getopts "u:n:r:d:s:C:F:K:P:B:E:X:R:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        n) SENDER_NODES=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        d) DURATION=$OPTARG ;;
        s) SITE=$OPTARG ;;
        C) COOJA_PATH=$OPTARG ;;
        F) FIRMWARE_FITIOT=$OPTARG ;;
        K) FIRMWARE_COOJA=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        B) CSMA_MIN_BE=$OPTARG ;;
        E) CSMA_MAX_BE=$OPTARG ;;
        X) CSMA_MAX_BACKOFF=$OPTARG ;;
        R) CSMA_MAX_FRAME_RETRIES=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

# ---------- Derived values --------------------------------------------------
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
EXP_NAME="exp_${TIMESTAMP}"
RESULTS_BASE="$REPO_DIR/results/$EXP_NAME"
FITIOT_DIR="$RESULTS_BASE/fitiot"
COOJA_DIR="$RESULTS_BASE/cooja"
SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
ALL_NODES="${RECEIVER_NODE}+${SENDER_NODES}"
NB_SENDERS=$(echo $SENDER_NODES | tr '+' '\n' | wc -l)

mkdir -p "$FITIOT_DIR" "$COOJA_DIR"

echo "=============================================="
echo " Unified Experiment: FIT IoT-LAB + Cooja"
echo "=============================================="
echo " Nodes     : receiver=m3-$RECEIVER_NODE  senders=m3-$(echo $SENDER_NODES | tr '+' ',')"
echo " Duration  : $DURATION min"
echo " Packets   : $NB_PACKETS per burst"
echo " CSMA      : min_be=$CSMA_MIN_BE max_be=$CSMA_MAX_BE max_backoff=$CSMA_MAX_BACKOFF max_frame_retries=$CSMA_MAX_FRAME_RETRIES"
echo " Results   : $RESULTS_BASE"
echo "=============================================="

# =============================================================================
# STEP 1 — Compile Cooja firmware with requested NB_PACKETS + CSMA config
# =============================================================================
echo ""
echo "[1/7] Compiling Cooja firmware (NB_PACKETS=$NB_PACKETS, CSMA=$CSMA_MIN_BE/$CSMA_MAX_BE/$CSMA_MAX_BACKOFF/$CSMA_MAX_FRAME_RETRIES)..."

make -C "$FIRMWARE_COOJA" clean > /dev/null 2>&1
make -C "$FIRMWARE_COOJA" NB_PACKETS="$NB_PACKETS" \
    CSMA_MIN_BE="$CSMA_MIN_BE" CSMA_MAX_BE="$CSMA_MAX_BE" \
    CSMA_MAX_BACKOFF="$CSMA_MAX_BACKOFF" CSMA_MAX_FRAME_RETRIES="$CSMA_MAX_FRAME_RETRIES" \
    > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo "  ✗ Cooja firmware compilation failed — aborting"
    exit 1
fi
echo "  ✓ Firmware compiled: sender + receiver (NB_PACKETS=$NB_PACKETS)"

# =============================================================================
# STEP 2 — Fetch node positions from FIT IoT-LAB
# =============================================================================
echo ""
echo "[2/7] Fetching node positions from FIT IoT-LAB..."

POSITIONS_FILE="$RESULTS_BASE/node_positions.json"

python3 "$REPO_DIR/tools/get_fitiot_positions.py" \
    --host "$SSH_HOST" \
    --nodes "$ALL_NODES" \
    --receiver "$RECEIVER_NODE" \
    --output "$POSITIONS_FILE"

if [ $? -ne 0 ] || [ ! -f "$POSITIONS_FILE" ]; then
    echo "  ✗ Failed to fetch positions"
    exit 1
fi
echo "  ✓ Positions saved: $POSITIONS_FILE"

# =============================================================================
# STEP 3 — Generate Cooja .csc with real IoT-LAB positions
# =============================================================================
echo ""
echo "[3/7] Generating Cooja simulation file with IoT-LAB positions..."

CSC_FILE="$RESULTS_BASE/simulation.csc"

python3 "$REPO_DIR/tools/generate_csc.py" \
    --template "$REPO_DIR/templates/radio-link-quality.csc" \
    --positions "$POSITIONS_FILE" \
    --firmware-dir "$FIRMWARE_COOJA" \
    --duration "$DURATION" \
    --output "$CSC_FILE"

if [ $? -ne 0 ] || [ ! -f "$CSC_FILE" ]; then
    echo "  ✗ Failed to generate .csc file"
    exit 1
fi
echo "  ✓ Simulation file: $CSC_FILE"

# =============================================================================
# STEP 4 — Run FIT IoT-LAB and Cooja IN PARALLEL
# =============================================================================
echo ""
echo "[4/7] Launching FIT IoT-LAB and Cooja in parallel..."

# --- Cooja headless in background (no stdin needed) ---
bash "$REPO_DIR/tools/run_cooja.sh" \
    -C "$COOJA_PATH" \
    -f "$CSC_FILE" \
    -d "$DURATION" \
    -o "$COOJA_DIR" </dev/null &
COOJA_PID=$!
echo "  → Cooja running in background (PID $COOJA_PID)..."

# --- FIT IoT-LAB in foreground (serial_aggregator needs SSH stdin) ---
echo "  → Starting FIT IoT-LAB experiment (foreground)..."
bash "$REPO_DIR/tools/run_fitiot.sh" \
    -u "$USER_LOGIN" \
    -n "$SENDER_NODES" \
    -r "$RECEIVER_NODE" \
    -d "$DURATION" \
    -s "$SITE" \
    -o "$FITIOT_DIR" \
    -F "$FIRMWARE_FITIOT" \
    -P "$NB_PACKETS" \
    -B "$CSMA_MIN_BE" -E "$CSMA_MAX_BE" \
    -K "$CSMA_MAX_BACKOFF" -R "$CSMA_MAX_FRAME_RETRIES"
FITIOT_STATUS=$?

# --- Wait for Cooja to finish ---
echo "  → Waiting for Cooja to finish..."
wait $COOJA_PID
COOJA_STATUS=$?

if [ $FITIOT_STATUS -ne 0 ]; then
    echo "  ⚠ FIT IoT-LAB experiment failed (check $FITIOT_DIR)"
fi
if [ $COOJA_STATUS -ne 0 ]; then
    echo "  ⚠ Cooja simulation failed (check $COOJA_DIR)"
fi

if [ $FITIOT_STATUS -ne 0 ] && [ $COOJA_STATUS -ne 0 ]; then
    echo "  ✗ Both experiments failed — aborting"
    exit 1
fi
echo "  ✓ Both experiments finished"

# =============================================================================
# STEP 5 — Normalize Cooja log to FIT IoT-LAB format
# =============================================================================
echo ""
echo "[5/7] Normalizing Cooja log format..."

if [ -f "$COOJA_DIR/loglistener.txt" ]; then
    python3 "$REPO_DIR/tools/convert_cooja_log.py" \
        --input "$COOJA_DIR/loglistener.txt" \
        --output "$COOJA_DIR/serial.log"

    if [ $? -eq 0 ]; then
        echo "  ✓ Cooja log normalized: $COOJA_DIR/serial.log"
    else
        echo "  ⚠ Log conversion failed"
    fi
else
    echo "  ⚠ Cooja loglistener.txt not found"
fi

# =============================================================================
# STEP 6 — Run analysis on both logs
# =============================================================================
echo ""
echo "[6/7] Computing metrics..."

if [ -f "$FITIOT_DIR/serial.log" ]; then
    echo "  → FIT IoT-LAB metrics:"
    python3 "$REPO_DIR/tools/run_analysis.py" \
        --dir     "$FITIOT_DIR" \
        --nodes   "$NB_SENDERS" \
        --oml-dir "$FITIOT_DIR"
else
    echo "  ⚠ FIT IoT-LAB serial.log not found — skipping"
fi

if [ -f "$COOJA_DIR/serial.log" ]; then
    echo "  → Cooja metrics:"
    python3 "$REPO_DIR/tools/run_analysis.py" \
        --dir   "$COOJA_DIR" \
        --nodes "$NB_SENDERS"
else
    echo "  ⚠ Cooja serial.log not found — skipping"
fi

# =============================================================================
# STEP 7 — Generate comparison graphs
# =============================================================================
echo ""
echo "[7/7] Generating comparison graphs..."

python3 "$REPO_DIR/tools/plot_comparison.py" \
    --fitiot-dir "$FITIOT_DIR" \
    --cooja-dir  "$COOJA_DIR" \
    --output-dir "$RESULTS_BASE"

cat > "$RESULTS_BASE/experiment_info.txt" << EXPEOF
Experiment  : $EXP_NAME
Date        : $(date)
Site        : $SITE
Receiver    : m3-$RECEIVER_NODE
Senders     : m3-$(echo $SENDER_NODES | tr '+' ',')
Nb senders  : $NB_SENDERS
Duration    : $DURATION min
Packets     : $NB_PACKETS per burst
CSMA config : min_be=$CSMA_MIN_BE max_be=$CSMA_MAX_BE max_backoff=$CSMA_MAX_BACKOFF max_frame_retries=$CSMA_MAX_FRAME_RETRIES
EXPEOF

echo ""
echo "=============================================="
echo " ALL DONE"
echo "=============================================="
echo " Results: $RESULTS_BASE"
echo " Graphs : $RESULTS_BASE/*.png"
echo "=============================================="
