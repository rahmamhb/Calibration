#!/bin/bash
# =============================================================================
# run_fitiot_only.sh
# Runs a standalone FIT IoT-LAB experiment, computes metrics and plots results
#
# Usage:
#   ./run_fitiot_only.sh [options]
#
# Options:
#   -u  username                (default: mihoub)
#   -n  sender node IDs         (default: 3+4+5)
#   -r  receiver node ID        (default: 2)
#   -d  duration minutes        (default: 5)
#   -s  site                    (default: grenoble)
#   -F  firmware dir on IoT-LAB (default: ~/iot-lab/parts/contiki/examples/radio-link-quality)
#   -P  packets per burst       (default: 1)
#   -B  CSMA_MIN_BE             (default: 0)
#   -E  CSMA_MAX_BE             (default: 4)
#   -K  CSMA_MAX_BACKOFF        (default: 5)
#   -R  CSMA_MAX_FRAME_RETRIES  (default: 7)
# =============================================================================

# ---------- Defaults --------------------------------------------------------
USER_LOGIN="mihoub"
SENDER_NODES="3+4+5"
RECEIVER_NODE="2"
DURATION=60
SITE="grenoble"
FIRMWARE_FITIOT="~/iot-lab/parts/contiki/examples/radio-link-quality"
NB_PACKETS=1
CSMA_MIN_BE=0
CSMA_MAX_BE=4
CSMA_MAX_BACKOFF=5
CSMA_MAX_FRAME_RETRIES=7
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- Parse arguments -------------------------------------------------
while getopts "u:n:r:d:s:F:P:D:B:E:K:R:" opt; do
    case $opt in
        u) USER_LOGIN=$OPTARG ;;
        n) SENDER_NODES=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        d) DURATION=$OPTARG ;;
        s) SITE=$OPTARG ;;
        F) FIRMWARE_FITIOT=$OPTARG ;;
        P) NB_PACKETS=$OPTARG ;;
        D) PHASE_DURATION_S=$OPTARG ;;
        B) CSMA_MIN_BE=$OPTARG ;;
        E) CSMA_MAX_BE=$OPTARG ;;
        K) CSMA_MAX_BACKOFF=$OPTARG ;;
        R) CSMA_MAX_FRAME_RETRIES=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

# ---------- Derived values --------------------------------------------------
# Default to 4 equal phases if -D was not given
: "${PHASE_DURATION_S:=$(( DURATION * 60 / 4 ))}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
EXP_NAME="fitiot_${TIMESTAMP}"
RESULTS_BASE="$SCRIPT_DIR/results/$EXP_NAME"
FITIOT_DIR="$RESULTS_BASE/fitiot"
SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
ALL_NODES="${RECEIVER_NODE}+${SENDER_NODES}"
NB_SENDERS=$(echo $SENDER_NODES | tr '+' '\n' | wc -l)

mkdir -p "$FITIOT_DIR"

echo "=============================================="
echo " FIT IoT-LAB Standalone Experiment"
echo "=============================================="
echo " Nodes     : receiver=m3-$RECEIVER_NODE  senders=m3-$(echo $SENDER_NODES | tr '+' ',')"
echo " Duration  : $DURATION min"
echo " Senders   : $NB_SENDERS"
echo " Packets   : $NB_PACKETS per burst"
echo " Site      : $SITE"
echo " CSMA      : min_be=$CSMA_MIN_BE max_be=$CSMA_MAX_BE max_backoff=$CSMA_MAX_BACKOFF max_frame_retries=$CSMA_MAX_FRAME_RETRIES"
echo " Results   : $RESULTS_BASE"
echo "=============================================="

# =============================================================================
# STEP 1 — Fetch node positions
# =============================================================================
echo ""
echo "[1/5] Fetching node positions from FIT IoT-LAB..."

POSITIONS_FILE="$RESULTS_BASE/node_positions.json"

python3 "$SCRIPT_DIR/tools/get_fitiot_positions.py" \
    --host "$SSH_HOST" \
    --nodes "$ALL_NODES" \
    --receiver "$RECEIVER_NODE" \
    --output "$POSITIONS_FILE"

if [ $? -ne 0 ] || [ ! -f "$POSITIONS_FILE" ]; then
    echo "  ✗ Failed to fetch positions — aborting"
    exit 1
fi
echo "  ✓ Positions saved: $POSITIONS_FILE"

# =============================================================================
# STEP 2 — Run FIT IoT-LAB experiment
# =============================================================================
echo ""
echo "[2/5] Running FIT IoT-LAB experiment..."

FIT_ARGS=(-u "$USER_LOGIN" -n "$SENDER_NODES" -r "$RECEIVER_NODE" \
          -d "$DURATION"  -s "$SITE"         -o "$FITIOT_DIR" \
          -F "$FIRMWARE_FITIOT" -P "$NB_PACKETS" \
          -B "$CSMA_MIN_BE" -E "$CSMA_MAX_BE" \
          -K "$CSMA_MAX_BACKOFF" -R "$CSMA_MAX_FRAME_RETRIES")
[ -n "$PHASE_DURATION_S" ] && FIT_ARGS+=(-D "$PHASE_DURATION_S")

bash "$SCRIPT_DIR/tools/run_fitiot.sh" "${FIT_ARGS[@]}"

if [ $? -ne 0 ]; then
    echo "  ✗ FIT IoT-LAB experiment failed — aborting"
    exit 1
fi
echo "  ✓ Experiment complete"

# =============================================================================
# STEP 3 — Run analysis
# =============================================================================
echo ""
echo "[3/5] Computing metrics..."

if [ ! -f "$FITIOT_DIR/serial.log" ]; then
    echo "  ✗ serial.log not found in $FITIOT_DIR — aborting"
    exit 1
fi

python3 "$SCRIPT_DIR/tools/run_analysis.py" \
    --dir     "$FITIOT_DIR" \
    --nodes   "$NB_SENDERS" \
    --oml-dir "$FITIOT_DIR"
ANALYSIS_STATUS=$?

if [ $ANALYSIS_STATUS -ne 0 ] || [ ! -f "$FITIOT_DIR/metrics.csv" ]; then
    echo "  ✗ Analysis failed or metrics.csv not produced — aborting"
    exit 1
fi
echo "  ✓ Metrics saved: $FITIOT_DIR/metrics.csv"

# =============================================================================
# STEP 4 — Save experiment summary
# =============================================================================
echo ""
echo "[4/5] Saving experiment summary..."

{
cat << EXPEOF
Experiment  : $EXP_NAME
Date        : $(date)
Site        : $SITE
Receiver    : m3-$RECEIVER_NODE
Senders     : m3-$(echo $SENDER_NODES | tr '+' ',')
Nb senders  : $NB_SENDERS
Duration    : $DURATION min
CSMA config : min_be=$CSMA_MIN_BE max_be=$CSMA_MAX_BE max_backoff=$CSMA_MAX_BACKOFF max_frame_retries=$CSMA_MAX_FRAME_RETRIES
EXPEOF

# tx_power phase firmware (Firmwares/senderTX.c) auto-switches TX power on a
# timer — only meaningful when that firmware is actually deployed.
if [[ "$FIRMWARE_FITIOT" == *senderTX* || "$FIRMWARE_FITIOT" == *tx_power* ]]; then
cat << EXPEOF
Phase dur   : ${PHASE_DURATION_S}s per phase
Phases      :
  Phase 0  STABLE    0 dBm   (firmware auto-switch)
  Phase 1  DEGRADED -9 dBm
  Phase 2  RECOVERY -5 dBm
  Phase 3  CRITICAL -17 dBm
Phase log   : (generated by firmware PHASE markers in serial.log)
EXPEOF
fi
} > "$RESULTS_BASE/experiment_info.txt"

echo "  ✓ Summary saved: $RESULTS_BASE/experiment_info.txt"

# =============================================================================
# STEP 5 — Plot standalone FIT IoT-LAB metrics
# =============================================================================
echo ""
echo "[5/5] Plotting metrics..."

python3 "$SCRIPT_DIR/tools/plot_single.py" \
    --dir        "$FITIOT_DIR" \
    --label      "FIT IoT-LAB" \
    --output-dir "$RESULTS_BASE"

if [ $? -eq 0 ]; then
    echo "  ✓ Plots saved: $RESULTS_BASE/*.png"
else
    echo "  ⚠ Plotting failed — metrics are still available in $FITIOT_DIR/metrics.json"
fi

echo ""
echo "=============================================="
echo " FIT IoT-LAB DONE"
echo "=============================================="
echo " Results   : $RESULTS_BASE"
echo " Log       : $FITIOT_DIR/serial.log"
echo " Metrics   : $FITIOT_DIR/metrics.csv"
echo " Positions : $POSITIONS_FILE"
echo " Plots     : $RESULTS_BASE/*.png"
echo "=============================================="