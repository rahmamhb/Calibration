#!/usr/bin/env python3
"""
adaptive_monitor.py  —  runs directly on the CRAN server
Place at: ~/cooja-sim/adaptive_monitor.py

Usage:
    python3 adaptive_monitor.py \
        --log results/Scenario04/synthetic_logs_v2/synthetic_serial.log \
        --window 30 --step 10 --delta 0.5 --realtime --speed 60

    # Live deployment (log is actively being written):
    python3 adaptive_monitor.py \
        --log /path/to/live_serial.log \
        --window 30 --step 10 --delta 0.5 --live
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── local tools ───────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from kpi_extractor   import extract_kpis
from change_detector import PageHinkley
from sender_roles    import find_node_positions, get_main_senders

# ─────────────────────────────────────────────────────────────
# CONFIG  (all local — no SSH)
# ─────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent          # ~/cooja-sim/
RESULTS_DIR   = BASE_DIR / "results"
MODELS_DIR    = Path("/home/mihoubrahma/Calibration models")
POSITIONS     = BASE_DIR / "node_positions.json"
TEMPLATES_DIR = BASE_DIR / "templates"
MSG_SIZE      = 8
N_NODES       = 20

RETRIGGER_LOSS_THRESHOLD = 5.0   # % — re-calibrate if accumulated Δloss exceeds this

RESULT_COLS = [
    "window_id", "window_start_s", "window_end_s", "change_detected",
    "real_mean_rssi", "real_loss_rate", "real_throughput",
    "real_mean_delay", "real_std_delay", "real_min_rssi",
    "real_std_rssi", "real_std_loss", "real_min_prr",
    "pred_path_loss", "pred_awgn", "pred_inflection", "pred_rx_sens",
    "sim_mean_rssi", "sim_loss_rate", "sim_throughput",
    "sim_mean_delay", "sim_std_delay", "sim_min_rssi",
    "delta_rssi", "delta_loss", "delta_throughput", "delta_delay",
]

# ─────────────────────────────────────────────────────────────
# STEP 4 — NN INFERENCE  (local call, no SSH)
# ─────────────────────────────────────────────────────────────

def run_nn_inference(kpis):
    kpi_str = ",".join([
        str(round(kpis[k], 6)) for k in [
            "mean_rssi_dbm", "std_rssi_dbm", "min_rssi_dbm",
            "loss_rate_pct", "throughput_pkt_s",
            "mean_delay_s", "std_delay_s",
            "std_loss_rate", "per_node_min_prr",
        ]
    ])
    cmd = [sys.executable,
           str(BASE_DIR / "predict_params.py"),
           f"--kpis={kpi_str}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [NN ERROR] {r.stderr.strip()}")
        return None
    parts = r.stdout.strip().split(",")
    if len(parts) != 4:
        print(f"  [NN ERROR] unexpected output: {r.stdout.strip()}")
        return None
    return {
        "path_loss_exponent":    float(parts[0]),
        "awgn_sigma":            float(parts[1]),
        "rssi_inflection_point": float(parts[2]),
        "rx_sensitivity":        float(parts[3]),
    }

# ─────────────────────────────────────────────────────────────
# STEPS 5–6 — CSC GENERATION + COOJA  (local, no SSH)
# ─────────────────────────────────────────────────────────────

def run_cooja_simulation(params, window_id, n_nodes, run_dir, sim_duration_min=2,
                          positions_path=POSITIONS):
    import glob as _glob, shutil as _shutil
    sim_dir = run_dir / f"window_{window_id:04d}"
    sim_dir.mkdir(parents=True, exist_ok=True)

    # Run Cooja — pass predicted radio params directly via run_cooja_only.sh flags
    # (avoids a redundant intermediate CSC that run_cooja_only.sh would regenerate
    # with its own defaults, discarding the NN-predicted values)
    sim_cmd = [
        "bash", str(BASE_DIR / "run_cooja_only.sh"),
        "-d", str(sim_duration_min),
        "-p", str(positions_path),
        "-g", "40",
        "-e", f"{params['path_loss_exponent']:.4f}",
        "-w", f"{params['awgn_sigma']:.4f}",
        "-i", f"{params['rssi_inflection_point']:.4f}",
        "-x", f"{params['rx_sensitivity']:.4f}",
    ]
    print(f"  [SIM] Running Cooja for window {window_id} ...")
    r = subprocess.run(sim_cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    if r.returncode != 0:
        print(f"  [SIM ERROR] {r.stderr.strip()[:200]}")
        return None

    # 7 — find the cooja output folder just created and move it under sim_dir
    cooja_runs = sorted(_glob.glob(str(BASE_DIR / "results" / "cooja_*")))
    if not cooja_runs:
        print(f"  [ERROR] cooja output folder not found")
        return None
    cooja_out = Path(cooja_runs[-1])
    dest = sim_dir / "cooja_out"
    _shutil.move(str(cooja_out), str(dest))

    # metrics.csv is produced by run_cooja_only.sh internally
    metrics_src = dest / "cooja" / "metrics.csv"
    metrics_dst = sim_dir / "sim_metrics.csv"
    if metrics_src.exists():
        metrics_dst.write_bytes(metrics_src.read_bytes())
    return sim_dir

# ─────────────────────────────────────────────────────────────
# STEP 7 — READ RESULTS  (local, no SCP)
# ─────────────────────────────────────────────────────────────

def collect_results(sim_dir):
    mpath = sim_dir / "sim_metrics.csv"
    if not mpath.exists():
        print(f"  [ERROR] sim_metrics.csv not found in {sim_dir}")
        return None
    with open(mpath) as f:
        for row in csv.DictReader(f):
            return row
    return None

# ─────────────────────────────────────────────────────────────
# BACKGROUND SIMULATION THREAD
# ─────────────────────────────────────────────────────────────

def _run_sim_bg(params, wid, n_nodes, run_dir, sim_duration_min,
               trigger_kpis, result_dict, lock, positions_path=POSITIONS):
    """Target for the background simulation thread.
    Writes into result_dict under lock when finished.
    """
    sim_dir  = run_cooja_simulation(params, wid, n_nodes, run_dir, sim_duration_min,
                                     positions_path=positions_path)
    sim_kpis = collect_results(sim_dir) if sim_dir else None
    with lock:
        result_dict["sim_dir"]      = sim_dir
        result_dict["sim_kpis"]     = sim_kpis
        result_dict["trigger_kpis"] = trigger_kpis

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def append_result(out_path, row):
    exists = Path(out_path).exists()
    with open(out_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_COLS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


def safe(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def compute_allowed_senders(log_path, senders_arg, auto_detect_main,
                            start_frac, end_frac):
    """Mirrors kpi_extractor.extract_kpis' sender-restriction logic, so the
    resimulated CSC uses the same node set as the real KPIs it's measured
    against — otherwise calibration would simulate interferer nodes that
    the real-side KPI already excluded.
    Returns a set of 'm3-XXX' labels, or None if no restriction applies.
    """
    if senders_arg:
        return {n.strip() if n.strip().startswith("m3-") else f"m3-{n.strip()}"
                for n in senders_arg.split(',') if n.strip()}
    if auto_detect_main:
        allowed, _source = get_main_senders(log_path, send_events=None,
                                            start_frac=start_frac, end_frac=end_frac)
        return allowed
    return None


def filter_positions_to_senders(positions_path, allowed, out_path):
    """Write a copy of `positions_path` keeping only the receiver + nodes
    in `allowed` (a set of 'm3-XXX' labels). Returns `positions_path`
    unchanged if `allowed` is None (detection inconclusive)."""
    if allowed is None:
        return positions_path
    allowed_ids = {a.replace("m3-", "") for a in allowed}
    with open(positions_path) as f:
        data = json.load(f)
    data["nodes"] = {
        nid: info for nid, info in data["nodes"].items()
        if info.get("role") == "receiver" or nid in allowed_ids
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    return str(out_path)

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--log",      required=True)
    p.add_argument("--window",   type=int,   default=30)
    p.add_argument("--step",     type=int,   default=10)
    p.add_argument("--delta",    type=float, default=0.5)
    p.add_argument("--nodes",    type=int,   default=N_NODES)
    p.add_argument("--realtime", action="store_true",
                   help="Throttle reading to simulate real time (replay mode)")
    p.add_argument("--speed",    type=float, default=10.0,
                   help="Playback speed multiplier (default: 10 — realistic for "
                        "demo; use 1 for true real-time, 60 for fast sweep)")
    p.add_argument("--sim-duration", type=int, default=2,
                   dest="sim_duration",
                   help="Simulated duration passed to Cooja in minutes (default: 2)")
    p.add_argument("--live",     action="store_true",
                   help="Tail the log file live — for real deployments where the "
                        "log is actively being written. Overrides --realtime/--speed.")
    p.add_argument("--retrigger-threshold", type=float,
                   default=RETRIGGER_LOSS_THRESHOLD,
                   dest="retrigger_threshold",
                   help="Re-calibrate if mean real loss during simulation diverges "
                        "from sim prediction by more than this %% (default: %(default)s)")
    p.add_argument("--senders", default=None,
                   help="Comma-separated node IDs to restrict KPI computation to, "
                        "e.g. '218,216,226,228,227'. Overrides auto-detection. "
                        "Use when the log mixes a main flow with interferer/background "
                        "traffic and you only want to monitor the main flow.")
    p.add_argument("--no-auto-detect-main", action="store_true",
                   help="Disable automatic main-vs-interferer sender detection "
                        "(see tools/sender_roles.py) — fall back to monitoring "
                        "every sender node. Ignored if --senders is given.")
    p.add_argument("--start-frac", type=float, default=0.05,
                   help="Auto-detection heuristic: a node must send within this "
                        "fraction of the experiment span from the start to count "
                        "as a main sender (default: %(default)s)")
    p.add_argument("--end-frac", type=float, default=0.05,
                   help="Auto-detection heuristic: a node must send within this "
                        "fraction of the experiment span from the end to count "
                        "as a main sender (default: %(default)s)")
    p.add_argument("--positions", default=None,
                   help="node_positions.json to use for calibration re-simulations. "
                        "Default: auto-detect the one sitting next to --log's experiment "
                        "(e.g. results/ScenarioNN/node_positions.json), falling back to "
                        f"{POSITIONS} if none is found nearby.")
    p.add_argument("--out",      default="adaptive_results.csv")
    return p.parse_args()


def main():
    args    = parse_args()
    ts      = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"adaptive_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_csv = run_dir / args.out

    detector = PageHinkley(delta=0.5, threshold=5.0, burn_in=3, cooldown=10)
    wid      = 0

    if args.positions:
        positions_path = Path(args.positions)
        positions_source = "manual"
    else:
        found = find_node_positions(args.log)
        positions_path = Path(found) if found else POSITIONS
        positions_source = "auto-detected" if found else "default (none found near log)"

    # Restrict the resimulated CSC to the same senders the real KPIs are
    # computed over — without this, calibration runs simulate interferer
    # nodes that the real-side KPI extraction already excluded.
    allowed_senders = compute_allowed_senders(
        args.log, args.senders, not args.no_auto_detect_main,
        args.start_frac, args.end_frac)
    if allowed_senders:
        filtered_path = run_dir / "calibration_positions.json"
        positions_path = Path(filter_positions_to_senders(
            str(positions_path), allowed_senders, filtered_path))
        positions_source += f"  →  filtered to {sorted(allowed_senders)} (+ receiver)"

    # ── Background simulation state ───────────────────────────
    sim_thread    = None          # threading.Thread or None
    sim_result    = {}            # filled by _run_sim_bg when done
    sim_lock      = threading.Lock()
    accum_windows = []            # real windows accumulated while sim runs
    pending_row   = None          # CSV row waiting for sim results
    calib_wid     = None          # window_id that triggered current sim

    print("=" * 60)
    print("Adaptive calibration monitor  (server mode)")
    print(f"  Log      : {args.log}")
    print(f"  Window   : {args.window}s   Step: {args.step}s   δ: {args.delta}")
    if args.live:
        print(f"  Mode     : LIVE (tailing log file)")
    else:
        print(f"  Realtime : {args.realtime}  Speed: {args.speed}x")
    print(f"  Sim duration : {args.sim_duration} min (Cooja simulated time)")
    print(f"  Retrigger threshold: {args.retrigger_threshold}% accumulated Δloss")
    print(f"  Positions: {positions_path}  [{positions_source}]")
    print(f"  Output   : {out_csv}")
    print("=" * 60)

    for kpis, w_start, w_end in extract_kpis(
            args.log, window_s=args.window, step_s=args.step,
            n_nodes=args.nodes, msg_size=MSG_SIZE,
            realtime=args.realtime, speed=args.speed,
            live=args.live,
            senders=args.senders,
            auto_detect_main=not args.no_auto_detect_main,
            start_frac=args.start_frac, end_frac=args.end_frac):

        wid += 1
        force_recalib = False

        # ── 1. Check if background sim just finished ──────────
        if sim_thread is not None and not sim_thread.is_alive():
            with sim_lock:
                res = dict(sim_result)
            sim_thread = None

            sim_dir    = res.get("sim_dir")
            sim_kpis   = res.get("sim_kpis")
            t_kpis     = res.get("trigger_kpis", {})

            print(f"\n  ┌─ CALIBRATION DONE (triggered at W{calib_wid:03d}) "
                  + "─" * 20)

            # Fill sim columns on the pending row and write it now
            if pending_row is not None:
                if sim_kpis:
                    d_rssi  = abs(t_kpis.get("mean_rssi_dbm", 0)    - safe(sim_kpis.get("mean_rssi_dbm")))
                    d_loss  = abs(t_kpis.get("loss_rate_pct", 0)    - safe(sim_kpis.get("loss_rate_pct")))
                    d_tput  = abs(t_kpis.get("throughput_pkt_s", 0) - safe(sim_kpis.get("throughput_pkt_s")))
                    d_delay = abs(t_kpis.get("mean_delay_s", 0)     - safe(sim_kpis.get("mean_delay_s")))
                    pending_row.update({
                        "sim_mean_rssi":    sim_kpis.get("mean_rssi_dbm", ""),
                        "sim_loss_rate":    sim_kpis.get("loss_rate_pct", ""),
                        "sim_throughput":   sim_kpis.get("throughput_pkt_s", ""),
                        "sim_mean_delay":   sim_kpis.get("mean_delay_s", ""),
                        "sim_std_delay":    sim_kpis.get("std_delay_s", ""),
                        "sim_min_rssi":     sim_kpis.get("min_rssi_dbm", ""),
                        "delta_rssi":       round(d_rssi,  4),
                        "delta_loss":       round(d_loss,  4),
                        "delta_throughput": round(d_tput,  4),
                        "delta_delay":      round(d_delay, 6),
                    })
                    print(f"  │  Fidelity: ΔRSSI={d_rssi:.2f} dBm  "
                          f"Δloss={d_loss:.2f}%  Δdelay={d_delay:.4f}s")
                else:
                    print(f"  │  Simulation failed — no fidelity metrics")
                append_result(out_csv, pending_row)
                pending_row = None

            # ── Post-sim retrigger check ──────────────────────
            if accum_windows:
                mean_real_loss = sum(w["loss_rate_pct"] for w in accum_windows) / len(accum_windows)
                sim_loss       = safe(sim_kpis.get("loss_rate_pct")) if sim_kpis else 0.0
                accum_delta    = abs(mean_real_loss - sim_loss)
                n_acc          = len(accum_windows)
                print(f"  │  {n_acc} windows during calibration: "
                      f"mean_real_loss={mean_real_loss:.1f}%  "
                      f"sim_loss={sim_loss:.1f}%  Δ={accum_delta:.1f}%")
                if accum_delta > args.retrigger_threshold:
                    print(f"  │  Δ={accum_delta:.1f}% > {args.retrigger_threshold}% threshold "
                          f"→ RE-TRIGGERING calibration")
                    force_recalib = True
                else:
                    print(f"  │  Network stable — no re-trigger needed")

            print(f"  └─" + "─" * 38 + "\n")
            accum_windows = []
            calib_wid     = None

        # ── 2. Window print & change detection ────────────────
        sim_tag = (f"  [calibrating W{calib_wid:03d}]"
                   if sim_thread is not None else "")
        print(f"[W{wid:03d}] {w_start:.0f}–{w_end:.0f}s  "
              f"RSSI={kpis['mean_rssi_dbm']:.1f}dBm  "
              f"loss={kpis['loss_rate_pct']:.1f}%  "
              f"tput={kpis['throughput_pkt_s']:.2f}  "
              f"delay={kpis['mean_delay_s']:.3f}s"
              + sim_tag)

        changed = detector.update(kpis["loss_rate_pct"])

        # Accumulate this window while a sim is running
        if sim_thread is not None:
            accum_windows.append(kpis)

        row = {
            "window_id": wid, "window_start_s": round(w_start),
            "window_end_s": round(w_end), "change_detected": int(changed),
            "real_mean_rssi":  kpis["mean_rssi_dbm"],
            "real_loss_rate":  kpis["loss_rate_pct"],
            "real_throughput": kpis["throughput_pkt_s"],
            "real_mean_delay": kpis["mean_delay_s"],
            "real_std_delay":  kpis["std_delay_s"],
            "real_min_rssi":   kpis["min_rssi_dbm"],
            "real_std_rssi":   kpis["std_rssi_dbm"],
            "real_std_loss":   kpis["std_loss_rate"],
            "real_min_prr":    kpis["per_node_min_prr"],
        }

        # ── 3. If sim already running, don't launch another ───
        #    Write every window (including change-detected ones) so the CSV is
        #    complete. The post-sim retrigger handles re-calibration when done.
        if sim_thread is not None and sim_thread.is_alive() and not force_recalib:
            append_result(out_csv, row)
            continue

        if not changed and not force_recalib:
            append_result(out_csv, row)
            continue

        # ── 4. Change detected (or retrigger) — recalibrate ───
        reason = "Re-calibrating (retrigger)" if force_recalib else "Change detected — recalibrating"
        print(f"  → {reason} in background ...")

        if kpis["loss_rate_pct"] < 2.0:
            print("  → Network recovered (loss < 2%) — skipping calibration")
            append_result(out_csv, row)
            continue

        params = run_nn_inference(kpis)
        if params is None:
            append_result(out_csv, row)
            continue

        print(f"  → PL={params['path_loss_exponent']:.3f}  "
              f"σ={params['awgn_sigma']:.3f}  "
              f"infl={params['rssi_inflection_point']:.1f}  "
              f"rx_sens={params['rx_sensitivity']:.1f}")

        infl_margin = kpis["mean_rssi_dbm"] - params["rssi_inflection_point"]
        if infl_margin > 15.0:
            print(f"  [WARN] inflection={params['rssi_inflection_point']:.1f} is "
                  f"{infl_margin:.1f} dB below actual RSSI={kpis['mean_rssi_dbm']:.1f} — "
                  f"sim loss will likely be underestimated (model out of training range)")
        print(f"  → Simulation launched in background — "
              f"log reading continues uninterrupted")

        # Keep the row; sim columns will be filled when the thread finishes
        row.update({
            "pred_path_loss":  params["path_loss_exponent"],
            "pred_awgn":       params["awgn_sigma"],
            "pred_inflection": params["rssi_inflection_point"],
            "pred_rx_sens":    params["rx_sensitivity"],
        })
        row["change_detected"] = 1
        pending_row = row

        with sim_lock:
            sim_result.clear()

        sim_thread = threading.Thread(
            target=_run_sim_bg,
            args=(params, wid, args.nodes, run_dir, args.sim_duration,
                  kpis, sim_result, sim_lock, positions_path),
            daemon=True,
        )
        sim_thread.start()
        calib_wid     = wid
        accum_windows = []

    # ── End of log — wait for any still-running sim ───────────
    if sim_thread is not None and sim_thread.is_alive():
        print(f"\n  [END] All log windows read. Calibration (W{calib_wid:03d}) still running "
              f"in background — waiting for it to finish ...")
        print(f"  [END] (This gap is expected for finite/synthetic logs replayed faster "
              f"than real time. Use --speed 1 to avoid it.)")
        sim_thread.join()
        with sim_lock:
            res = dict(sim_result)
        sim_kpis = res.get("sim_kpis")
        t_kpis   = res.get("trigger_kpis", {})
        if pending_row is not None and sim_kpis:
            d_rssi  = abs(t_kpis.get("mean_rssi_dbm", 0)    - safe(sim_kpis.get("mean_rssi_dbm")))
            d_loss  = abs(t_kpis.get("loss_rate_pct", 0)    - safe(sim_kpis.get("loss_rate_pct")))
            d_tput  = abs(t_kpis.get("throughput_pkt_s", 0) - safe(sim_kpis.get("throughput_pkt_s")))
            d_delay = abs(t_kpis.get("mean_delay_s", 0)     - safe(sim_kpis.get("mean_delay_s")))
            pending_row.update({
                "sim_mean_rssi":    sim_kpis.get("mean_rssi_dbm", ""),
                "sim_loss_rate":    sim_kpis.get("loss_rate_pct", ""),
                "sim_throughput":   sim_kpis.get("throughput_pkt_s", ""),
                "sim_mean_delay":   sim_kpis.get("mean_delay_s", ""),
                "sim_std_delay":    sim_kpis.get("std_delay_s", ""),
                "sim_min_rssi":     sim_kpis.get("min_rssi_dbm", ""),
                "delta_rssi":       round(d_rssi,  4),
                "delta_loss":       round(d_loss,  4),
                "delta_throughput": round(d_tput,  4),
                "delta_delay":      round(d_delay, 6),
            })
            print(f"  [END] Fidelity: ΔRSSI={d_rssi:.2f} dBm  "
                  f"Δloss={d_loss:.2f}%  Δdelay={d_delay:.4f}s")
        if pending_row is not None:
            append_result(out_csv, pending_row)

    print(f"\nDone. {wid} windows. Results → {out_csv}")


if __name__ == "__main__":
    main()
