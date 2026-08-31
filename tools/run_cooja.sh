#!/bin/bash
# =============================================================================
# run_cooja.sh
# Runs Cooja headlessly — log is captured by the ScriptRunner in the .csc
# (injected by generate_csc.py) which writes directly to loglistener.txt
#
# -d is a hard timeout (in minutes) in case Cooja hangs — it is NOT the
# simulation duration. The script waits for Cooja to exit naturally first.
# =============================================================================

COOJA_PATH=""
CSC_FILE=""
MAX_WAIT_MIN=30      # hard timeout in minutes (default: 30 min wall clock)
OUTPUT_DIR=""

while getopts "C:f:d:o:" opt; do
    case $opt in
        C) COOJA_PATH=$OPTARG ;;
        f) CSC_FILE=$OPTARG ;;
        d) MAX_WAIT_MIN=$OPTARG ;;
        o) OUTPUT_DIR=$OPTARG ;;
        *) echo "Unknown option: -$opt"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

# ScriptRunner in the .csc writes here (set by generate_csc.py)
CSC_DIR="$(dirname "$CSC_FILE")"
LISTENER_FILE="$CSC_DIR/cooja/loglistener.txt"
COOJA_LOG="$OUTPUT_DIR/cooja.log"

MAX_WAIT_SECONDS=$(( MAX_WAIT_MIN * 60 ))
POLL_INTERVAL=10

echo "  [Cooja] Starting headless simulation..."
echo "  [Cooja] Hard timeout: ${MAX_WAIT_MIN} min (wall clock)"

# Try Gradle-based Cooja (newer)
if [ -f "$COOJA_PATH/gradlew" ]; then
    "$COOJA_PATH/gradlew" --project-dir "$COOJA_PATH" run \
        --args="--no-gui $CSC_FILE" \
        > "$COOJA_LOG" 2>&1 &
    COOJA_PID=$!

# Try JAR-based Cooja (older)
elif [ -f "$COOJA_PATH/dist/cooja.jar" ]; then
    java -jar "$COOJA_PATH/dist/cooja.jar" \
        --no-gui \
        --logdir="$OUTPUT_DIR" \
        "$CSC_FILE" \
        > "$COOJA_LOG" 2>&1 &
    COOJA_PID=$!

else
    echo "  [Cooja] ✗ Cooja not found at: $COOJA_PATH"
    exit 1
fi

# Poll until Cooja exits naturally (ScriptRunner calls log.testOK() on timeout)
# or until the hard wall-clock timeout is reached
elapsed=0
while kill -0 $COOJA_PID 2>/dev/null; do
    sleep $POLL_INTERVAL
    elapsed=$(( elapsed + POLL_INTERVAL ))
    echo "  [Cooja] Still running... ${elapsed}s elapsed"

    if [ $elapsed -ge $MAX_WAIT_SECONDS ]; then
        echo "  [Cooja] ⚠ Hard timeout reached after ${MAX_WAIT_MIN} min — killing..."
        kill $COOJA_PID
        wait $COOJA_PID 2>/dev/null
        echo "           Check $COOJA_LOG for errors"
        exit 1
    fi
done

wait $COOJA_PID
EXIT_CODE=$?
echo "  [Cooja] Process exited (code $EXIT_CODE) after ${elapsed}s"

# Copy log to output dir
if [ -f "$LISTENER_FILE" ]; then
    cp "$LISTENER_FILE" "$OUTPUT_DIR/loglistener.txt"
    echo "  [Cooja] ✓ Log saved: $OUTPUT_DIR/loglistener.txt"
else
    echo "  [Cooja] ✗ Log not found at: $LISTENER_FILE"
    echo "           Check $COOJA_LOG for errors"
    exit 1
fi