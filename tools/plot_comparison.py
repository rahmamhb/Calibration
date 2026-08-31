#!/usr/bin/env python3
# =============================================================================
# plot_comparison.py
#
# Comparison visualization: FIT IoT-LAB vs Cooja.
# Plots: metrics bar chart, delay CDF, and RSSI boxplot (only if present in logs).
#
# Usage:
#   python3 plot_comparison.py \
#       --fitiot-dir <fitiot_results_dir> \
#       --cooja-dir  <cooja_results_dir> \
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

COLOR_FIT   = "#2196F3"
COLOR_COOJA = "#FF5722"


def load_metrics(results_dir):
    csv_path = os.path.join(results_dir, "metrics.csv")
    if not os.path.exists(csv_path):
        return None
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            return {k: float(v) for k, v in row.items() if v not in (None, "")}
    return None


def load_node_mapping(results_dir):
    """Returns (uid_to_node, cooja_to_fit) from node_positions.json one level above results_dir."""
    positions_path = os.path.join(os.path.dirname(results_dir), "node_positions.json")
    uid_to_node  = {}
    cooja_to_fit = {}

    if not os.path.exists(positions_path):
        print(f"⚠ node_positions.json not found at {positions_path}")
        return uid_to_node, cooja_to_fit

    with open(positions_path) as f:
        data = json.load(f)

    for node_id, info in data.get("nodes", {}).items():
        uid = info.get("uid", "").lower()
        if uid:
            uid_to_node[uid] = f"m3-{node_id}"
        cooja_id = info.get("cooja_id")
        if cooja_id is not None:
            cooja_to_fit[str(cooja_id)] = f"m3-{node_id}"

    return uid_to_node, cooja_to_fit


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


def plot_metrics(fitiot_metrics, cooja_metrics, output_path):
    metric_keys   = ["mean_delay_s", "loss_rate_pct", "throughput_pkt_s", "per_node_min_prr"]
    metric_labels = ["Delay (s)", "Loss Rate (%)", "Throughput (pkt/s)", "Min PRR (%)"]

    fig, axes = plt.subplots(1, len(metric_keys), figsize=(4.5 * len(metric_keys), 5))
    fig.suptitle("FIT IoT-LAB vs Cooja — Metrics", fontsize=14, fontweight="bold")

    for ax, key, label in zip(axes, metric_keys, metric_labels):
        vals, colors, xlabels = [], [], []
        for m, color, name in [
            (fitiot_metrics, COLOR_FIT,   "FIT IoT-LAB"),
            (cooja_metrics,  COLOR_COOJA, "Cooja"),
        ]:
            if m:
                v = m.get(key, 0)
                vals.append(v * 100 if key == "per_node_min_prr" else v)
                colors.append(color)
                xlabels.append(name)

        if vals:
            bars = ax.bar(xlabels, vals, color=colors, width=0.4, edgecolor="white")
            for bar in bars:
                h = bar.get_height()
                ax.annotate(f"{h:.3f}",
                            (bar.get_x() + bar.get_width() / 2, h),
                            xytext=(0, 4), textcoords="offset points",
                            ha="center", fontsize=10)
        ax.set_title(label, fontsize=11)
        ax.set_ylabel(label)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Metrics graph: {output_path}")


def plot_rssi(fitiot_rssi, cooja_rssi, output_path):
    all_senders = sorted(set(list(fitiot_rssi.keys()) + list(cooja_rssi.keys())))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    fig.suptitle("FIT IoT-LAB vs Cooja — RSSI per Sender", fontsize=14, fontweight="bold")

    for ax, rssi_dict, color, title in [
        (ax1, fitiot_rssi, COLOR_FIT,   "FIT IoT-LAB"),
        (ax2, cooja_rssi,  COLOR_COOJA, "Cooja"),
    ]:
        data   = [rssi_dict[s] for s in all_senders if s in rssi_dict and rssi_dict[s]]
        labels = [s for s in all_senders if s in rssi_dict and rssi_dict[s]]

        if data:
            bp = ax.boxplot(data, tick_labels=labels, patch_artist=True,
                            medianprops=dict(color="white", linewidth=2),
                            whiskerprops=dict(linewidth=1.5),
                            capprops=dict(linewidth=1.5))
            for patch in bp["boxes"]:
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
            for i, d in enumerate(data):
                ax.scatter(i + 1, np.mean(d), color='green', marker='D', s=50, zorder=3,
                           label='Mean' if i == 0 else '')
            ax.legend(loc='upper right')
        else:
            ax.text(0.5, 0.5, "No RSSI data",
                    ha='center', va='center', transform=ax.transAxes, fontsize=11)

        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_ylabel("RSSI (dBm)")
        ax.set_xlabel("Sender node")
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        ax.set_ylim(-100, -5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ RSSI graph: {output_path}")


def plot_delay_cdf(fitiot_timeline, cooja_timeline, output_path):
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.suptitle("FIT IoT-LAB vs Cooja — Packet Delay CDF", fontsize=14, fontweight="bold")

    plotted = False
    for timeline, color, label in [
        (fitiot_timeline, COLOR_FIT,   "FIT IoT-LAB"),
        (cooja_timeline,  COLOR_COOJA, "Cooja"),
    ]:
        delays = sorted(r - s for s, r in timeline if r is not None and r >= s)
        if delays:
            cdf = np.arange(1, len(delays) + 1) / len(delays)
            ax.plot(delays, cdf, label=f"{label} (n={len(delays)})", color=color, linewidth=2)
            plotted = True

    if not plotted:
        ax.text(0.5, 0.5, "No delay data",
                ha='center', va='center', transform=ax.transAxes, fontsize=12)

    ax.set_xlabel("Delay (s)")
    ax.set_ylabel("CDF")
    ax.legend(loc='lower right')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Delay CDF graph: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fitiot-dir",  required=True, help="Directory with FIT IoT-LAB results")
    parser.add_argument("--cooja-dir",   required=True, help="Directory with Cooja results")
    parser.add_argument("--output-dir",  required=True, help="Output directory for graphs")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    uid_to_node, _ = load_node_mapping(args.fitiot_dir)

    fitiot_metrics = load_metrics(args.fitiot_dir)
    cooja_metrics  = load_metrics(args.cooja_dir)
    print(f"→ FIT metrics  : {fitiot_metrics or 'not found'}")
    print(f"→ Cooja metrics: {cooja_metrics or 'not found'}")

    fitiot_rssi = parse_rssi(os.path.join(args.fitiot_dir, "serial.log"), uid_to_node, is_cooja=False)
    cooja_rssi  = parse_rssi(os.path.join(args.cooja_dir,  "serial.log"), None,         is_cooja=True)
    has_rssi = bool(fitiot_rssi or cooja_rssi)
    print(f"→ RSSI         : {'found' if has_rssi else 'not found — skipping RSSI plot'}")

    fitiot_timeline = parse_timeline(os.path.join(args.fitiot_dir, "serial.log"))
    cooja_timeline  = parse_timeline(os.path.join(args.cooja_dir,  "serial.log"))
    print(f"→ FIT timeline : {len(fitiot_timeline)} events")
    print(f"→ Cooja timeline: {len(cooja_timeline)} events")

    plot_metrics(
        fitiot_metrics, cooja_metrics,
        os.path.join(args.output_dir, "metrics_comparison.png")
    )

    if has_rssi:
        plot_rssi(
            fitiot_rssi, cooja_rssi,
            os.path.join(args.output_dir, "rssi_comparison.png")
        )

    plot_delay_cdf(
        fitiot_timeline, cooja_timeline,
        os.path.join(args.output_dir, "delay_cdf.png")
    )

    print(f"\n✓ All graphs saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
