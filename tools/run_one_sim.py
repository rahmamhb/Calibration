#!/usr/bin/env python3
"""
run_one_sim.py
──────────────
Runs the full pipeline for ONE parameter combination and appends
one row to dataset.csv. Called by submit_dataset.sh via sbatch.

Updated to match new run_analysis.py output (9 metrics, single row).
"""

import argparse
import csv
import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

PROJECT_DIR      = "/home/mihoubrahma/cooja-sim"
DATASET_CSV      = f"{PROJECT_DIR}/dataset.csv"
WORK_DIR         = f"{PROJECT_DIR}/dataset_runs"

TOOLS_DIR        = f"{PROJECT_DIR}/tools"
COOJA_PATH       = "/home/mihoubrahma/contiki-ng/tools/cooja"
TEMPLATE         = f"{PROJECT_DIR}/templates/radio-link-quality.csc"
POSITIONS_FILE   = f"{PROJECT_DIR}/node_positions.json"
FIRMWARE_DIR     = "/home/mihoubrahma/contiki-ng/examples/radio-link-quality"
NB_SENDERS       = 5
SIM_DURATION_MIN = 5
WALL_TIMEOUT_MIN = 60

# ── CSV COLUMNS ───────────────────────────────────────────────────────────────

PARAM_COLS = [
    "id",
    "RX_SENSITIVITY_DBM",
    "RSSI_INFLECTION_POINT",
    "TRANSMITTING_RANGE",
    "PATH_LOSS_EXPONENT",
    "AWGN_SIGMA",
]

METRIC_COLS = [
    "mean_rssi_dbm",
    "std_rssi_dbm",
    "min_rssi_dbm",
    "loss_rate_pct",
    "throughput_pkt_s",
    "mean_delay_s",
    "std_delay_s",
    "std_loss_rate",
    "per_node_min_prr",
]

ALL_COLS = PARAM_COLS + METRIC_COLS

# ── HELPERS ───────────────────────────────────────────────────────────────────

def run_cmd(cmd, label, timeout_sec=None):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
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


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id",                     required=True)
    parser.add_argument("--rx-sensitivity",         required=True)
    parser.add_argument("--rssi-inflection-point",  required=True)
    parser.add_argument("--transmitting-range",     required=True)
    parser.add_argument("--path-loss-exponent",     required=True)
    parser.add_argument("--awgn-sigma",             required=True)
    parser.add_argument("--random-seed",            default=None)
    args = parser.parse_args()

    sim_id    = args.id
    sim_dir   = Path(WORK_DIR) / f"sim_{sim_id}"
    cooja_dir = sim_dir / "cooja"
    sim_dir.mkdir(parents=True, exist_ok=True)
    cooja_dir.mkdir(parents=True, exist_ok=True)

    csc_path = sim_dir / "simulation.csc"
    t0 = time.time()

    print(f"\n[sim {sim_id}] Starting — "
          f"rip={args.rssi_inflection_point} "
          f"tr={args.transmitting_range} "
          f"ple={args.path_loss_exponent} "
          f"awgn={args.awgn_sigma}")

    # STEP 1 — generate .csc
    print(f"[sim {sim_id}] [1/4] Generating .csc...")
    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/generate_csc.py",
        "--template",              TEMPLATE,
        "--positions",             POSITIONS_FILE,
        "--firmware-dir",          FIRMWARE_DIR,
        "--duration",              str(SIM_DURATION_MIN),
        "--output",                str(csc_path),
        "--rx-sensitivity",        args.rx_sensitivity,
        "--rssi-inflection-point", args.rssi_inflection_point,
        "--transmitting-range",    args.transmitting_range,
        "--path-loss-exponent",    args.path_loss_exponent,
        "--awgn-sigma",            args.awgn_sigma,
        *( ["--random-seed", args.random_seed] if args.random_seed else [] ),
    ], "generate_csc.py")
    if not ok:
        sys.exit(1)

    # STEP 2 — run Cooja
    print(f"[sim {sim_id}] [2/4] Running Cooja...")
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
    print(f"[sim {sim_id}] [3/4] Converting log...")
    log_listener = cooja_dir / "loglistener.txt"
    serial_log   = cooja_dir / "serial.log"

    if not log_listener.exists():
        print(f"[sim {sim_id}] [ERROR] loglistener.txt not found")
        sys.exit(1)

    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/convert_cooja_log.py",
        "--input",  str(log_listener),
        "--output", str(serial_log),
    ], "convert_cooja_log.py")
    if not ok:
        sys.exit(1)

    # STEP 4 — run analysis → metrics.csv (single row, 9 metrics)
    print(f"[sim {sim_id}] [4/4] Running analysis...")
    ok = run_cmd([
        "python3", f"{TOOLS_DIR}/run_analysis.py",
        "--dir",   str(cooja_dir),
        "--nodes", str(NB_SENDERS),
    ], "run_analysis.py")

    metrics_path = cooja_dir / "metrics.csv"
    if not ok or not metrics_path.exists():
        print(f"[sim {sim_id}] [ERROR] metrics.csv not produced")
        sys.exit(1)

    with open(metrics_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"[sim {sim_id}] [ERROR] metrics.csv is empty")
        sys.exit(1)

    m = rows[0]

    elapsed = time.time() - t0
    print(f"[sim {sim_id}] ✓ Done in {elapsed:.0f}s — "
          f"rssi={m.get('mean_rssi_dbm','?')} dBm  "
          f"loss={m.get('loss_rate_pct','?')}%  "
          f"tput={m.get('throughput_pkt_s','?')}  "
          f"delay={m.get('mean_delay_s','?')}s")

    row = {
        "id":                    sim_id,
        "RX_SENSITIVITY_DBM":    args.rx_sensitivity,
        "RSSI_INFLECTION_POINT": args.rssi_inflection_point,
        "TRANSMITTING_RANGE":    args.transmitting_range,
        "PATH_LOSS_EXPONENT":    args.path_loss_exponent,
        "AWGN_SIGMA":            args.awgn_sigma,
        "mean_rssi_dbm":         m.get("mean_rssi_dbm",    ""),
        "std_rssi_dbm":          m.get("std_rssi_dbm",     ""),
        "min_rssi_dbm":          m.get("min_rssi_dbm",     ""),
        "loss_rate_pct":         m.get("loss_rate_pct",    ""),
        "throughput_pkt_s":      m.get("throughput_pkt_s", ""),
        "mean_delay_s":          m.get("mean_delay_s",     ""),
        "std_delay_s":           m.get("std_delay_s",      ""),
        "std_loss_rate":         m.get("std_loss_rate",    ""),
        "per_node_min_prr":      m.get("per_node_min_prr", ""),
    }
    append_row_safe(DATASET_CSV, row)
    print(f"[sim {sim_id}] ✓ Row written to dataset.csv")

    # shutil.rmtree(sim_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
