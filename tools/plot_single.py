#!/usr/bin/env python3
# =============================================================================
# plot_single.py
#
# Single experiment visualization (FIT IoT-LAB or Cooja).
# Plots: metrics bar chart, delay CDF, and RSSI boxplot (only if present in log).
#
# Usage:
#   python3 plot_single.py \
#       --dir <results_dir> \
#       --label "FIT IoT-LAB" \
#       --output-dir <output_dir>
# =============================================================================

import argparse
import csv
import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLOR = "#4C9BE8"


def load_metrics(results_dir):
    csv_path = os.path.join(results_dir, "metrics.csv")
    if not os.path.exists(csv_path):
        print(f"⚠ metrics.csv not found in {results_dir}")
        return {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            return {k: float(v) for k, v in row.items() if v not in (None, "")}
    return {}


def load_node_mapping(results_dir):
    """Returns UID → m3-X mapping from node_positions.json one level above results_dir."""
    positions_path = os.path.join(os.path.dirname(results_dir), "node_positions.json")
    if not os.path.exists(positions_path):
        return {}
    with open(positions_path) as f:
        data = json.load(f)
    return {
        info.get("uid", "").lower(): f"m3-{node_id}"
        for node_id, info in data.get("nodes", {}).items()
        if info.get("uid")
    }


def parse_rssi(serial_path, uid_to_node, is_cooja):
    """Returns {sender_label: [rssi, ...]} or empty dict if no RSSI in log."""
    rssi_by_sender = {}
    if not os.path.exists(serial_path):
        return rssi_by_sender

    with open(serial_path) as f:
        for line in f:
            if "CSMA" in line:
                continue
            if ";r " not in line and ";r\t" not in line:
                continue
            rssi_match = re.search(r'rssi=(-?\d+)', line)
            if not rssi_match:
                continue
            rssi = int(rssi_match.group(1))

            sender_match = re.search(r';r\s+([0-9a-f:]+)\s+', line)
            if not sender_match:
                continue
            last_seg = sender_match.group(1).split(':')[-1]

            if is_cooja:
                label = f"m3-{last_seg}" if last_seg.isdigit() else last_seg
            else:
                label = uid_to_node.get(last_seg, last_seg)

            rssi_by_sender.setdefault(label, []).append(rssi)

    return rssi_by_sender


def parse_timeline(serial_path):
    """Returns list of (send_ts, recv_ts) pairs for matched packets."""
    packets = {}
    if not os.path.exists(serial_path):
        return []

    with open(serial_path) as f:
        for line in f:
            if "CSMA" in line:
                continue
            m = re.match(r"^([\d.]+);[^;]+;([sr])\s+([0-9a-f:]+)\s+([0-9a-f]+)", line)
            if not m:
                continue
            ts, event, ipv6, pid = float(m.group(1)), m.group(2), m.group(3), m.group(4)
            key = ipv6.split(':')[-1] + pid
            if event == 's':
                packets[key] = [ts, None]
            elif event == 'r' and key in packets:
                packets[key][1] = ts

    return [(s, r) for s, r in packets.values() if s is not None]


def plot_all(metrics, rssi_data, timeline, label, output_dir):
    has_rssi = bool(rssi_data)
    ncols = 3 if has_rssi else 2
    fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, 5))

    fig.suptitle(label, fontsize=14, fontweight="bold")

    # ── Metrics bar chart ──────────────────────────────────────────────────────
    ax = axes[0]
    metric_keys   = ["mean_delay_s", "loss_rate_pct", "throughput_pkt_s", "per_node_min_prr"]
    metric_labels = ["Delay (s)", "Loss (%)", "Throughput\n(pkt/s)", "Min PRR (%)"]
    values = [metrics.get(k, 0) for k in metric_keys]
    values[3] = values[3] * 100
    bars = ax.bar(metric_labels, values, color=COLOR)
    ax.set_title("Metrics")
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.3f}",
                    (bar.get_x() + bar.get_width() / 2, h),
                    textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # ── RSSI boxplot (only if data present) ───────────────────────────────────
    if has_rssi:
        ax = axes[1]
        data = list(rssi_data.values())
        labels = list(rssi_data.keys())
        bp = ax.boxplot(data, tick_labels=labels, patch_artist=True,
                        medianprops=dict(color="white", linewidth=2))
        for patch in bp["boxes"]:
            patch.set_facecolor(COLOR)
            patch.set_alpha(0.7)
        for i, d in enumerate(data):
            ax.scatter(i + 1, np.mean(d), marker='D', s=40, color='green', zorder=3)
        ax.set_title("RSSI per Sender")
        ax.set_ylabel("RSSI (dBm)")
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        cdf_ax = axes[2]
    else:
        cdf_ax = axes[1]

    # ── Delay CDF ─────────────────────────────────────────────────────────────
    delays = sorted(r - s for s, r in timeline if r is not None and r >= s)
    if delays:
        cdf = np.arange(1, len(delays) + 1) / len(delays)
        cdf_ax.plot(delays, cdf, linewidth=2, color=COLOR)
        cdf_ax.set_title(f"Delay CDF (n={len(delays)})")
    else:
        cdf_ax.text(0.5, 0.5, "No delay data",
                    ha="center", va="center", transform=cdf_ax.transAxes)
        cdf_ax.set_title("Delay CDF")
    cdf_ax.set_xlabel("Delay (s)")
    cdf_ax.set_ylabel("CDF")
    cdf_ax.grid(True, linestyle="--", alpha=0.5)
    cdf_ax.spines["top"].set_visible(False)
    cdf_ax.spines["right"].set_visible(False)

    # ── Save ──────────────────────────────────────────────────────────────────
    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    out_name = label.lower().replace(" ", "_")
    path = os.path.join(output_dir, f"single_{out_name}.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Plot saved: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir",        required=True, help="Directory containing metrics.csv and serial.log")
    parser.add_argument("--label",      required=True, help="Platform label (e.g. 'FIT IoT-LAB' or 'Cooja')")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    is_cooja = "cooja" in args.label.lower()
    serial_path = os.path.join(args.dir, "serial.log")

    metrics     = load_metrics(args.dir)
    uid_to_node = load_node_mapping(args.dir)
    rssi_data   = parse_rssi(serial_path, uid_to_node, is_cooja)
    timeline    = parse_timeline(serial_path)

    print(f"→ Metrics   : {metrics}")
    print(f"→ RSSI      : {'found (' + str(len(rssi_data)) + ' senders)' if rssi_data else 'not found — skipping RSSI plot'}")
    print(f"→ Timeline  : {len(timeline)} packet events")

    plot_all(metrics, rssi_data, timeline, args.label, args.output_dir)


if __name__ == "__main__":
    main()
