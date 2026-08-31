#!/usr/bin/env python3
# =============================================================================
# run_one_whatif_sim.py
# Runs the full pipeline for ONE (CSMA combo, topology) pair and appends one
# row to what-if/dataset.csv. Called by submit_whatif.sh via sbatch.
#
# Requires the firmware for this combo's (CSMA params, NB_PACKETS) key to
# already be cached — run prebuild_firmware.py first.
# =============================================================================

import argparse
import csv
import fcntl
import subprocess
import sys
import time
from pathlib import Path

from wi_common import (
    PROJECT_DIR, TEMPLATE_CSC, COOJA_PATH, DATASET_RUNS_DIR,
    LOGS_DIR, SIM_DURATION_MIN, WALL_TIMEOUT_MIN, TOPOLOGIES,
    firmware_key, firmware_cache_dir, dataset_csv_path,
)

TOOLS_DIR = f"{PROJECT_DIR}/tools"

# One dataset file per scenario (dataset_<topology>.csv) — "topology" is implied
# by the filename, not stored as a column.
PARAM_COLS = [
    "id",
    "CSMA_MIN_BE", "CSMA_MAX_BE", "CSMA_MAX_BACKOFF", "CSMA_MAX_FRAME_RETRIES",
    "RSSI_INFLECTION_POINT", "PATH_LOSS_EXPONENT", "AWGN_SIGMA",
]

METRIC_COLS = [
    "mean_rssi_dbm", "std_rssi_dbm", "min_rssi_dbm", "loss_rate_pct",
    "throughput_pkt_s", "mean_delay_s", "std_delay_s", "std_loss_rate",
    "per_node_min_prr",
]

ALL_COLS = PARAM_COLS + METRIC_COLS


def run_cmd(cmd, label, timeout_sec=None):
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout_sec,
        )
        out = result.stdout.decode(errors="replace").strip()
        if out:
            print(out)
        if result.returncode != 0:
            print(f"[ERROR] {label} failed (exit {result.returncode})")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"[WARN] {label} timed out")
        return False
    except Exception as e:
        print(f"[ERROR] {label}: {e}")
        return False


def append_row_safe(dataset_path, row):
    lock_path = dataset_path + ".lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        write_header = not Path(dataset_path).exists()
        with open(dataset_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ALL_COLS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
        fcntl.flock(lock_file, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id",                     required=True)
    parser.add_argument("--topology",                required=True, choices=list(TOPOLOGIES.keys()))
    parser.add_argument("--min-be",                  required=True, type=int)
    parser.add_argument("--max-be",                  required=True, type=int)
    parser.add_argument("--max-backoff",             required=True, type=int)
    parser.add_argument("--max-frame-retries",       required=True, type=int)
    args = parser.parse_args()

    sim_id   = args.id
    topology = args.topology
    topo     = TOPOLOGIES[topology]

    key = firmware_key(args.min_be, args.max_be, args.max_backoff, args.max_frame_retries,
                        topo["nb_packets"])
    firmware_dir = firmware_cache_dir(key)

    sender_bin   = Path(f"{firmware_dir}/build/z1/sender.z1")
    receiver_bin = Path(f"{firmware_dir}/build/z1/receiver.z1")
    if not sender_bin.exists() or not receiver_bin.exists():
        print(f"[sim {sim_id}/{topology}] [ERROR] firmware not prebuilt for key {key} "
              f"— run prebuild_firmware.py first")
        sys.exit(2)

    sim_dir   = Path(DATASET_RUNS_DIR) / f"sim_{sim_id}_{topology}"
    cooja_dir = sim_dir / "cooja"
    sim_dir.mkdir(parents=True, exist_ok=True)
    cooja_dir.mkdir(parents=True, exist_ok=True)

    csc_path = sim_dir / "simulation.csc"
    t0 = time.time()

    print(f"\n[sim {sim_id}/{topology}] Starting — "
          f"min_be={args.min_be} max_be={args.max_be} "
          f"max_backoff={args.max_backoff} max_frame_retries={args.max_frame_retries} "
          f"nb_packets={topo['nb_packets']} key={key}")

    # STEP 1 — generate .csc
    print(f"[sim {sim_id}/{topology}] [1/4] Generating .csc...")
    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/generate_csc.py",
        "--template",              TEMPLATE_CSC,
        "--positions",             topo["positions"],
        "--firmware-dir",          firmware_dir,
        "--duration",              str(SIM_DURATION_MIN),
        "--output",                str(csc_path),
        "--rx-sensitivity",        str(topo["rx_sensitivity"]),
        "--rssi-inflection-point", str(topo["rssi_inflection_point"]),
        "--path-loss-exponent",    str(topo["path_loss_exponent"]),
        "--awgn-sigma",            str(topo["awgn_sigma"]),
    ], "generate_csc.py")
    if not ok:
        sys.exit(1)

    # STEP 2 — run Cooja
    print(f"[sim {sim_id}/{topology}] [2/4] Running Cooja...")
    ok = run_cmd([
        "bash", f"{TOOLS_DIR}/run_cooja.sh",
        "-C", COOJA_PATH,
        "-f", str(csc_path.resolve()),
        "-d", str(WALL_TIMEOUT_MIN),
        "-o", str(cooja_dir.resolve()),
    ], "run_cooja.sh", timeout_sec=WALL_TIMEOUT_MIN * 60 + 120)
    if not ok:
        sys.exit(1)

    # STEP 3 — convert log
    print(f"[sim {sim_id}/{topology}] [3/4] Converting log...")
    log_listener = cooja_dir / "loglistener.txt"
    serial_log   = cooja_dir / "serial.log"

    if not log_listener.exists():
        print(f"[sim {sim_id}/{topology}] [ERROR] loglistener.txt not found")
        sys.exit(1)

    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/convert_cooja_log.py",
        "--input",  str(log_listener),
        "--output", str(serial_log),
    ], "convert_cooja_log.py")
    if not ok:
        sys.exit(1)

    # STEP 4 — run analysis -> metrics.csv
    print(f"[sim {sim_id}/{topology}] [4/4] Running analysis...")
    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/run_analysis.py",
        "--dir",   str(cooja_dir),
        "--nodes", str(topo["nb_senders"]),
    ], "run_analysis.py")

    metrics_path = cooja_dir / "metrics.csv"
    if not ok or not metrics_path.exists():
        print(f"[sim {sim_id}/{topology}] [ERROR] metrics.csv not produced")
        sys.exit(1)

    with open(metrics_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"[sim {sim_id}/{topology}] [ERROR] metrics.csv is empty")
        sys.exit(1)

    m = rows[0]
    elapsed = time.time() - t0
    print(f"[sim {sim_id}/{topology}] Done in {elapsed:.0f}s — "
          f"loss={m.get('loss_rate_pct','?')}%  tput={m.get('throughput_pkt_s','?')}  "
          f"delay={m.get('mean_delay_s','?')}s")

    row = {
        "id":                     sim_id,
        "CSMA_MIN_BE":            args.min_be,
        "CSMA_MAX_BE":            args.max_be,
        "CSMA_MAX_BACKOFF":       args.max_backoff,
        "CSMA_MAX_FRAME_RETRIES": args.max_frame_retries,
        "RSSI_INFLECTION_POINT":  topo["rssi_inflection_point"],
        "PATH_LOSS_EXPONENT":     topo["path_loss_exponent"],
        "AWGN_SIGMA":             topo["awgn_sigma"],
        "mean_rssi_dbm":          m.get("mean_rssi_dbm",    ""),
        "std_rssi_dbm":           m.get("std_rssi_dbm",     ""),
        "min_rssi_dbm":           m.get("min_rssi_dbm",     ""),
        "loss_rate_pct":          m.get("loss_rate_pct",    ""),
        "throughput_pkt_s":       m.get("throughput_pkt_s", ""),
        "mean_delay_s":           m.get("mean_delay_s",     ""),
        "std_delay_s":            m.get("std_delay_s",      ""),
        "std_loss_rate":          m.get("std_loss_rate",    ""),
        "per_node_min_prr":       m.get("per_node_min_prr", ""),
    }
    dataset_csv = dataset_csv_path(topology)
    append_row_safe(dataset_csv, row)
    print(f"[sim {sim_id}/{topology}] Row written to {dataset_csv}")


if __name__ == "__main__":
    main()
