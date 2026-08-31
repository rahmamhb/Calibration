#!/usr/bin/env python3
"""
plot_per_node_loss.py
Plots per-node packet loss for FIT IoT-LAB vs Cooja side by side,
using real m3 node labels (not Cooja IDs) for both platforms.

Usage:
    python3 tools/plot_per_node_loss.py \
        --fit-dir   results/Scenario05/fitiot_20260609_174432/fitiot \
        --cooja-dir results/Scenario05/cooja_20260612_110456/cooja \
        --pos       results/Scenario05/fitiot_20260609_174432/node_positions.json \
        --output    results/Scenario05/per_node_loss_comparison.png
"""

import argparse
import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIT_COLOR   = "#4C9BE8"
COOJA_COLOR = "#E87C4C"


# ── Mappings ──────────────────────────────────────────────────────────────────

def load_mappings(pos_file):
    """Returns (cooja_id_int → m3_label, uid_str → m3_label)."""
    with open(pos_file) as f:
        data = json.load(f)
    cooja_to_m3 = {}
    uid_to_m3   = {}
    for m3_id, info in data["nodes"].items():
        label = f"m3-{m3_id}"
        if "cooja_id" in info:
            cooja_to_m3[info["cooja_id"]] = label
        if "uid" in info:
            uid_to_m3[info["uid"]] = label
    return cooja_to_m3, uid_to_m3


# ── FIT parsing ───────────────────────────────────────────────────────────────

def parse_fit(serial_path, uid_to_m3, receiver="m3-125"):
    """
    Parse FIT serial.log.
    Sender lines:   <ts>;m3-<id>;s fe80::<uid> <seqno>
    Receiver lines: <ts>;m3-125;r fd00::<uid> <seqno>
    """
    sent = {}
    recv = {}
    with open(serial_path) as f:
        for line in f:
            parts = line.strip().split(";", 2)
            if len(parts) < 3:
                continue
            node, payload = parts[1], parts[2].split()
            if not payload:
                continue
            ev = payload[0]

            if ev == "s" and node != receiver:
                sent[node] = sent.get(node, 0) + 1

            elif ev == "r" and node == receiver and len(payload) >= 2:
                uid = payload[1].split(":")[-1]   # last segment of IPv6
                m3  = uid_to_m3.get(uid)
                if m3:
                    recv[m3] = recv.get(m3, 0) + 1

    return sent, recv


# ── Cooja parsing ─────────────────────────────────────────────────────────────

def parse_cooja(serial_path, cooja_to_m3, receiver_cooja_id=1):
    """
    Parse converted Cooja serial.log (FIT-compatible format, but Cooja IDs).
    Sender lines:   <ts>;m3-<cooja_id>;s fe80::c30c:0:0:<hex> <seqno>
    Receiver lines: <ts>;m3-1;r fe80::c30c:0:0:<hex> <seqno> rssi=...
    """
    sent = {}
    recv = {}
    receiver_node = f"m3-{receiver_cooja_id}"

    with open(serial_path) as f:
        for line in f:
            parts = line.strip().split(";", 2)
            if len(parts) < 3:
                continue
            node, payload = parts[1], parts[2].split()
            if not payload:
                continue
            ev = payload[0]

            try:
                cooja_id = int(node.split("-")[1])
            except (IndexError, ValueError):
                continue

            if ev == "s" and cooja_id != receiver_cooja_id:
                m3 = cooja_to_m3.get(cooja_id)
                if m3:
                    sent[m3] = sent.get(m3, 0) + 1

            elif ev == "r" and node == receiver_node and len(payload) >= 2:
                last_seg = payload[1].split(":")[-1]
                try:
                    sender_id = int(last_seg, 16)
                    m3 = cooja_to_m3.get(sender_id)
                    if m3:
                        recv[m3] = recv.get(m3, 0) + 1
                except ValueError:
                    pass

    return sent, recv


# ── Loss computation ──────────────────────────────────────────────────────────

def compute_loss(sent, recv):
    """Returns {m3_label: loss_pct}."""
    return {
        node: (sent[node] - recv.get(node, 0)) / sent[node] * 100
        for node in sent
        if sent[node] > 0
    }


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot(fit_loss, fit_sent, fit_recv,
         cooja_loss, cooja_sent, cooja_recv,
         output_path):

    all_nodes = sorted(
        set(fit_loss) | set(cooja_loss),
        key=lambda x: int(x.split("-")[1])
    )

    n     = len(all_nodes)
    x     = np.arange(n)
    width = 0.38

    # Use NaN for nodes absent from a platform so no bar is drawn
    fit_vals   = [fit_loss[nd]   if nd in fit_loss   else np.nan for nd in all_nodes]
    cooja_vals = [cooja_loss[nd] if nd in cooja_loss else np.nan for nd in all_nodes]

    fig, ax = plt.subplots(figsize=(max(12, n * 0.75), 6))

    bars_fit   = ax.bar(x - width / 2, fit_vals,   width,
                        label="FIT IoT-LAB",   color=FIT_COLOR,   alpha=0.85)
    bars_cooja = ax.bar(x + width / 2, cooja_vals, width,
                        label="Cooja (UDGM)", color=COOJA_COLOR, alpha=0.85)

    # Value annotations
    for bar, val, nd in zip(bars_fit, fit_vals, all_nodes):
        if not np.isnan(val) and val >= 0:
            s = fit_sent.get(nd, 0)
            r = fit_recv.get(nd, 0)
            ax.annotate(
                f"{val:.0f}%\n({r}/{s})",
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=6.5, color="#1a1a1a"
            )

    for bar, val, nd in zip(bars_cooja, cooja_vals, all_nodes):
        if not np.isnan(val) and val >= 0:
            s = cooja_sent.get(nd, 0)
            r = cooja_recv.get(nd, 0)
            ax.annotate(
                f"{val:.0f}%\n({r}/{s})",
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=6.5, color="#1a1a1a"
            )

    # Average lines (only over nodes with actual data)
    fit_mean   = np.nanmean(fit_vals)
    cooja_mean = np.nanmean(cooja_vals)
    ax.axhline(fit_mean,   color=FIT_COLOR,   linestyle="--", linewidth=1.2,
               label=f"FIT mean ({fit_mean:.1f}%)")
    ax.axhline(cooja_mean, color=COOJA_COLOR, linestyle="--", linewidth=1.2,
               label=f"Cooja mean ({cooja_mean:.1f}%)")

    ax.set_xlabel("Node", fontsize=12)
    ax.set_ylabel("Packet Loss (%)", fontsize=12)
    ax.set_title("Per-Node Packet Loss: FIT IoT-LAB vs Cooja (UDGM default)",
                 fontsize=13, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(all_nodes, rotation=45, ha="right", fontsize=9)
    ax.set_ylim(0, 115)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit-dir",   required=True)
    parser.add_argument("--cooja-dir", required=True)
    parser.add_argument("--pos",       required=True,
                        help="node_positions.json (same for both)")
    parser.add_argument("--output",    required=True)
    args = parser.parse_args()

    cooja_to_m3, uid_to_m3 = load_mappings(args.pos)

    fit_sent, fit_recv     = parse_fit(
        os.path.join(args.fit_dir,   "serial.log"), uid_to_m3)
    cooja_sent, cooja_recv = parse_cooja(
        os.path.join(args.cooja_dir, "serial.log"), cooja_to_m3)

    fit_loss   = compute_loss(fit_sent,   fit_recv)
    cooja_loss = compute_loss(cooja_sent, cooja_recv)

    print("\nFIT per-node loss:")
    for nd in sorted(fit_loss, key=lambda x: int(x.split("-")[1])):
        s, r = fit_sent.get(nd, 0), fit_recv.get(nd, 0)
        print(f"  {nd}: {fit_loss[nd]:.1f}%  (sent={s}, recv={r})")

    print("\nCooja per-node loss:")
    for nd in sorted(cooja_loss, key=lambda x: int(x.split("-")[1])):
        s, r = cooja_sent.get(nd, 0), cooja_recv.get(nd, 0)
        print(f"  {nd}: {cooja_loss[nd]:.1f}%  (sent={s}, recv={r})")

    plot(fit_loss, fit_sent, fit_recv,
         cooja_loss, cooja_sent, cooja_recv,
         args.output)


if __name__ == "__main__":
    main()
