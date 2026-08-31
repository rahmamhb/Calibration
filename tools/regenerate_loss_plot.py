#!/usr/bin/env python3
"""
Usage:
    python3 regenerate_loss_plot.py results/adaptive_20260625_073323
    python3 regenerate_loss_plot.py results/adaptive_20260613_142605
"""
import csv
import sys
from pathlib import Path


def regenerate(run_dir: Path):
    csv_path = run_dir / "adaptive_results.csv"
    if not csv_path.exists():
        print(f"✗ Not found: {csv_path}")
        sys.exit(1)

    real_loss, sim_baseline, sim_recalib, change_windows = [], [], [], []

    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            wid  = int(row["window_id"])
            loss = float(row["real_loss_rate"])
            real_loss.append((wid, int(row["window_start_s"]), loss))

            if row["change_detected"] == "1":
                change_windows.append(wid)

            if row["sim_loss_rate"] not in ("", None):
                entry = (wid, int(row["window_start_s"]), float(row["sim_loss_rate"]))
                if row["change_detected"] == "1":
                    sim_recalib.append(entry)
                else:
                    sim_baseline.append(entry)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 5))
    fig.patch.set_facecolor("#0d0f14")
    ax.set_facecolor("#13161e")
    for spine in ax.spines.values():
        spine.set_edgecolor("#252a38")
    ax.tick_params(colors="#6b7285", which="both")
    ax.xaxis.label.set_color("#6b7285")
    ax.yaxis.label.set_color("#6b7285")
    ax.title.set_color("#c8cdd8")

    # ── Dashed vertical lines at detection events ─────────────────────────────
    first = True
    for cw in change_windows:
        lbl = "Change detected" if first else None
        ax.axvline(cw, color="#ff5722", lw=1.2, ls="--", alpha=0.7, zorder=4, label=lbl)
        first = False

    # ── Real network: faded raw + rolling mean ± 5σ band ─────────────────────
    if real_loss:
        xs = [x[0] for x in real_loss]
        ys = [x[2] for x in real_loss]

        ax.plot(xs, ys, color="#1de9b6", lw=0.8, alpha=0.30, zorder=2)
        ax.fill_between(xs, ys, 0, alpha=0.05, color="#1de9b6")

        half = 2
        n = len(ys)
        roll_mean, roll_std = [], []
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            seg = ys[lo:hi]
            m = sum(seg) / len(seg)
            s = (sum((v - m) ** 2 for v in seg) / len(seg)) ** 0.5
            roll_mean.append(m)
            roll_std.append(s)

        upper = [m + 5 * s for m, s in zip(roll_mean, roll_std)]
        lower = [max(0.0, m - 5 * s) for m, s in zip(roll_mean, roll_std)]

        ax.fill_between(xs, lower, upper, alpha=0.18, color="#1de9b6",
                        zorder=2, label="Real ±5σ band")
        ax.plot(xs, roll_mean, color="#1de9b6", lw=1.8, zorder=3,
                label="Real network (rolling mean)")

    # ── Baseline simulation points (green squares) ────────────────────────────
    if sim_baseline:
        bx, by = zip(*[(x[0], x[2]) for x in sim_baseline])
        ax.scatter(bx, by, c="#69f0ae", s=90, zorder=5, marker="s",
                   label="Simulation (baseline)", edgecolors="#1b5e20", linewidths=0.8)

    # ── Recalibrated simulation points (orange triangles) ─────────────────────
    all_sim = sim_baseline + sim_recalib
    all_sim.sort(key=lambda x: x[0])
    if sim_recalib:
        cx, cy = zip(*[(x[0], x[2]) for x in sim_recalib])
        ax.scatter(cx, cy, c="#ffb300", s=90, zorder=5, marker="^",
                   label="Simulation (recalibrated)", edgecolors="#7a5200", linewidths=0.8)
    if len(all_sim) > 1:
        sx = [x[0] for x in all_sim]
        sy = [x[2] for x in all_sim]
        ax.plot(sx, sy, "--", color="#3e4559", lw=1, zorder=2)

    ax.set_xlabel("Window", color="#6b7285")
    ax.set_ylabel("Packet Loss Rate (%)", color="#6b7285")
    ax.set_title("Packet Loss Evolution — Real Network vs Simulation", color="#c8cdd8", pad=12)
    ax.grid(True, color="#252a38", linewidth=0.5, alpha=0.7)
    ax.legend(facecolor="#1a1e28", edgecolor="#252a38", labelcolor="#c8cdd8", fontsize=9)

    plt.tight_layout()

    # Use the existing plot filename if one is found, else default
    for candidate in ("packet_loss_evolution.png", "loss_evolution.png"):
        if (run_dir / candidate).exists():
            out = run_dir / candidate
            break
    else:
        out = run_dir / "loss_evolution.png"

    plt.savefig(str(out), dpi=150, bbox_inches="tight",
                facecolor="#0d0f14", edgecolor="none")
    plt.close()
    print(f"✓ Saved → {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 regenerate_loss_plot.py <run_dir>")
        sys.exit(1)
    regenerate(Path(sys.argv[1]))
