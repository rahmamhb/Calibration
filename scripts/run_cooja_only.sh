#!/bin/bash
# =============================================================================
# run_cooja_only.sh
# Runs a standalone Cooja simulation, computes metrics and plots results.
# Optionally compares against a fixed FIT IoT-LAB baseline.
#
# Usage:
#   ./run_cooja_only.sh [options]
#
# Options:
#   -n  sender node IDs         (default: 3+4+5)
#   -r  receiver node ID        (default: 2)
#   -d  duration minutes        (default: 5)   ← simulation duration
#   -C  cooja path              (default: ~/contiki-ng/tools/cooja)
#   -K  firmware dir            (pre-compiled; must contain build/z1/sender.z1 and build/z1/receiver.z1)
#   -T  template .csc           (default: ./templates/radio-link-quality.csc)
#   -p  positions JSON          (optional: skip fetching if already available)
#   -u  username for IoT-LAB    (default: mihoub, used only to fetch positions)
#   -s  site                    (default: grenoble, used only to fetch positions)
#   -b  FIT IoT-LAB baseline dir (optional: compare against fixed FIT results)
#   -S  speed limit             (default: -1 = unlimited/fastest possible)
#                                 use 1.0 to run at real time (benchmarking)
#                                 use 2.0 for 2× real time, etc.
# =============================================================================

# ---------- Defaults --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SENDER_NODES="3+4+5"
RECEIVER_NODE="2"
DURATION=60
COOJA_PATH="$HOME/contiki-ng/tools/cooja"
FIRMWARE_COOJA="$HOME/contiki-ng/examples/radio-link-quality/"
TEMPLATE="$REPO_DIR/templates/radio-link-quality.csc"
POSITIONS_FILE=""
USER_LOGIN="mihoub"
SITE="grenoble"
BASELINE_FITIOT_DIR=""
SPEED_LIMIT="-1"                 # -1 = unlimited (fastest), 1.0 = real time
NB_PACKETS=10

# ---------- Parse arguments -------------------------------------------------
while getopts "n:r:d:C:K:T:p:u:s:b:S:P:" opt; do
    case $opt in
        n) SENDER_NODES=$OPTARG ;;
        r) RECEIVER_NODE=$OPTARG ;;
        d) DURATION=$OPTARG ;;
        C) COOJA_PATH=$OPTARG ;;
        K) FIRMWARE_COOJA=$OPTARG ;;
        T) TEMPLATE=$OPTARG ;;
        p) POSITIONS_FILE=$OPTARG ;;
        u) USER_LOGIN=$OPTARG ;;
        s) SITE=$OPTARG ;;
        b) BASELINE_FITIOT_DIR=$OPTARG ;;
        S) SPEED_LIMIT=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

# ---------- Derived values --------------------------------------------------
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
EXP_NAME="cooja_${TIMESTAMP}"
RESULTS_BASE="$REPO_DIR/results/$EXP_NAME"
COOJA_DIR="$RESULTS_BASE/cooja"
SSH_HOST="${USER_LOGIN}@${SITE}.iot-lab.info"
ALL_NODES="${RECEIVER_NODE}+${SENDER_NODES}"
NB_SENDERS=$(echo $SENDER_NODES | tr '+' '\n' | wc -l)

# Human-readable speed label for display
if [ "$SPEED_LIMIT" = "-1" ]; then
    SPEED_LABEL="unlimited (fastest)"
elif [ "$SPEED_LIMIT" = "1.0" ] || [ "$SPEED_LIMIT" = "1" ]; then
    SPEED_LABEL="1× real time (benchmarking)"
else
    SPEED_LABEL="${SPEED_LIMIT}× real time"
fi

# ---------- Wall-clock timeout for run_cooja.sh (in minutes) ----------------
# Unlimited speed does NOT guarantee fast wall time — Z1 radio simulations
# often run at near-real-time. Use duration + 30 min buffer in both cases.
# If speed-limited: expected wall time = duration / speed_limit, + buffer.
if [ "$SPEED_LIMIT" = "-1" ]; then
    WALL_TIMEOUT_MIN=$(( DURATION + 30 ))
else
    WALL_TIMEOUT_MIN=$(echo "$DURATION $SPEED_LIMIT" | awk '{printf "%d", ($1 / $2) + 30}')
fi

mkdir -p "$COOJA_DIR"

echo "=============================================="
echo " Cooja Standalone Experiment"
echo "=============================================="
echo " Nodes     : receiver=m3-$RECEIVER_NODE  senders=m3-$(echo $SENDER_NODES | tr '+' ',')"
echo " Duration  : $DURATION min  (simulation time)"
echo " Senders   : $NB_SENDERS"
echo " Speed     : $SPEED_LABEL"
echo " Timeout   : ${WALL_TIMEOUT_MIN} min  (wall clock hard cap)"
echo " Results   : $RESULTS_BASE"
echo "=============================================="

# =============================================================================
# STEP 1 — Fetch node positions (skip if already provided via -p)
# =============================================================================
echo ""
echo "[1/5] Node positions..."

if [ -n "$POSITIONS_FILE" ] && [ -f "$POSITIONS_FILE" ]; then
    echo "  ✓ Using provided positions file: $POSITIONS_FILE"
    cp "$POSITIONS_FILE" "$RESULTS_BASE/node_positions.json"
    POSITIONS_FILE="$RESULTS_BASE/node_positions.json"
else
    POSITIONS_FILE="$RESULTS_BASE/node_positions.json"
    echo "  → Fetching from FIT IoT-LAB ($SSH_HOST)..."
    python3 "$REPO_DIR/tools/get_fitiot_positions.py" \
        --host "$SSH_HOST" \
        --nodes "$ALL_NODES" \
        --receiver "$RECEIVER_NODE" \
        --output "$POSITIONS_FILE"

    if [ $? -ne 0 ] || [ ! -f "$POSITIONS_FILE" ]; then
        echo "  ✗ Failed to fetch positions — aborting"
        exit 1
    fi
    echo "  ✓ Positions saved: $POSITIONS_FILE"
fi

# =============================================================================
# STEP 2 — Verify pre-compiled Cooja firmware exists
# =============================================================================
echo ""
echo "[2/5] Checking pre-compiled Cooja firmware..."

SENDER_FW="$FIRMWARE_COOJA/build/z1/sender.z1"
RECEIVER_FW="$FIRMWARE_COOJA/build/z1/receiver.z1"

if [ ! -f "$SENDER_FW" ]; then
    echo "  ✗ sender.z1 not found: $SENDER_FW"
    echo "  ℹ  Compile firmware in Docker and place the build/ output under $FIRMWARE_COOJA"
    exit 1
fi
if [ ! -f "$RECEIVER_FW" ]; then
    echo "  ✗ receiver.z1 not found: $RECEIVER_FW"
    echo "  ℹ  Compile firmware in Docker and place the build/ output under $FIRMWARE_COOJA"
    exit 1
fi
echo "  ✓ sender.z1  : $SENDER_FW"
echo "  ✓ receiver.z1: $RECEIVER_FW"
echo "  ℹ  NB_PACKETS=$NB_PACKETS must match the value used at compile time"

# =============================================================================
# STEP 3 — Generate Cooja .csc with real IoT-LAB positions and speed limit
# =============================================================================
echo ""
echo "[3/5] Generating Cooja simulation file with IoT-LAB positions..."

CSC_FILE="$RESULTS_BASE/simulation.csc"

python3 "$REPO_DIR/tools/generate_csc.py" \
    --template     "$TEMPLATE" \
    --positions    "$POSITIONS_FILE" \
    --firmware-dir "$FIRMWARE_COOJA" \
    --duration     "$DURATION" \
    --speed-limit  "$SPEED_LIMIT" \
    --output       "$CSC_FILE"

if [ $? -ne 0 ] || [ ! -f "$CSC_FILE" ]; then
    echo "  ✗ Failed to generate .csc file — aborting"
    exit 1
fi
echo "  ✓ Simulation file: $CSC_FILE"

# =============================================================================
# STEP 4 — Run Cooja headless
# =============================================================================
echo ""
echo "[4/5] Running Cooja simulation ($SPEED_LABEL)..."
echo "  ℹ  Simulation duration : ${DURATION} min (simulated time)"
echo "  ℹ  Wall-clock timeout  : ${WALL_TIMEOUT_MIN} min"

bash "$REPO_DIR/tools/run_cooja.sh" \
    -C "$COOJA_PATH" \
    -f "$CSC_FILE" \
    -d "$WALL_TIMEOUT_MIN" \
    -o "$COOJA_DIR"

if [ $? -ne 0 ]; then
    echo "  ✗ Cooja simulation failed — aborting"
    exit 1
fi
echo "  ✓ Simulation complete"

# =============================================================================
# STEP 5 — Normalize Cooja log to FIT IoT-LAB format
# =============================================================================
echo ""
echo "[5/5] Normalizing Cooja log format..."

if [ ! -f "$COOJA_DIR/loglistener.txt" ]; then
    echo "  ✗ loglistener.txt not found in $COOJA_DIR — aborting"
    exit 1
fi

python3 "$REPO_DIR/tools/convert_cooja_log.py" \
    --input  "$COOJA_DIR/loglistener.txt" \
    --output "$COOJA_DIR/serial.log"

if [ $? -ne 0 ]; then
    echo "  ✗ Log conversion failed — aborting"
    exit 1
fi
echo "  ✓ Log normalized: $COOJA_DIR/serial.log"

# =============================================================================
# POST — Compute metrics then plot
# =============================================================================
echo ""
echo "[+] Computing metrics and plotting..."

python3 "$REPO_DIR/tools/run_analysis.py" \
    --dir   "$COOJA_DIR" \
    --nodes "$NB_SENDERS"

if [ $? -ne 0 ] || [ ! -f "$COOJA_DIR/metrics.csv" ]; then
    echo "  ✗ Analysis failed or metrics.csv not produced — aborting"
    exit 1
fi
echo "  ✓ Metrics saved: $COOJA_DIR/metrics.csv"

# --- Now plot (requires metrics.csv to exist) ---
if [ -n "$BASELINE_FITIOT_DIR" ] && [ -d "$BASELINE_FITIOT_DIR" ]; then
    echo "  → Comparison mode: Cooja vs FIT IoT-LAB baseline ($BASELINE_FITIOT_DIR)"
    python3 "$REPO_DIR/tools/plot_comparison.py" \
        --fitiot-dir "$BASELINE_FITIOT_DIR" \
        --cooja-dir  "$COOJA_DIR" \
        --output-dir "$RESULTS_BASE"
else
    echo "  → Standalone mode: Cooja results only"
    echo "  ℹ  To compare against a FIT IoT-LAB baseline later, rerun with:"
    echo "     -b path/to/fitiot_exp/fitiot"
    python3 "$REPO_DIR/tools/plot_single.py" \
        --dir        "$COOJA_DIR" \
        --label      "Cooja" \
        --output-dir "$RESULTS_BASE"
fi

if [ $? -eq 0 ]; then
    echo "  ✓ Plots saved: $RESULTS_BASE/*.png"
else
    echo "  ⚠ Plotting failed — metrics are still available in $COOJA_DIR/metrics.csv"
fi

echo ""
echo "=============================================="
echo " COOJA DONE"
echo "=============================================="
echo " Results : $RESULTS_BASE"
echo " Log     : $COOJA_DIR/serial.log"
echo " Metrics : $COOJA_DIR/metrics.csv"
echo " Plots   : $RESULTS_BASE/*.png"
if [ -n "$BASELINE_FITIOT_DIR" ]; then
    echo " Baseline: $BASELINE_FITIOT_DIR"
fi
echo "=============================================="
