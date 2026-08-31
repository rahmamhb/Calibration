#!/usr/bin/env python3
"""
analyze_parameters.py
─────────────────────
Analyzes the effect of each LogisticLoss parameter on the 4 KPIs
using correlation, feature importance, and partial dependence plots.

Usage:
    python3 analyze_parameters.py --dataset dataset.csv
    python3 analyze_parameters.py --dataset dataset.csv --output analysis/

Requirements:
    pip install pandas numpy matplotlib seaborn scikit-learn scipy
"""

import argparse
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from scipy import stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import PartialDependenceDisplay
from sklearn.preprocessing import StandardScaler

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

PARAMS = [
    "RSSI_INFLECTION_POINT",
    "TRANSMITTING_RANGE",
    "PATH_LOSS_EXPONENT",
    "AWGN_SIGMA",
]

KPIS = [
    "mean_rssi_dbm",
    "loss_rate_pct",
    "throughput_pkt_s",
    "mean_delay_s",
]

KPI_LABELS = {
    "mean_rssi_dbm":    "Mean RSSI (dBm)",
    "loss_rate_pct":    "Loss rate (%)",
    "throughput_pkt_s": "Throughput (pkt/s)",
    "mean_delay_s":     "Mean delay (s)",
}

PARAM_LABELS = {
    "RSSI_INFLECTION_POINT": "RSSI inflection (dBm)",
    "TRANSMITTING_RANGE":    "TX range (m)",
    "PATH_LOSS_EXPONENT":    "Path loss exp.",
    "AWGN_SIGMA":            "AWGN sigma (dBm)",
}

# ── LOAD DATA ─────────────────────────────────────────────────────────────────

def load(path):
    df = pd.read_csv(path)
    df = df.dropna(subset=PARAMS + KPIS)
    print(f"Loaded {len(df)} rows from {path}")
    return df

# ── 1. CORRELATION MATRIX ─────────────────────────────────────────────────────

def plot_correlation(df, output_dir):
    print("\n[1/4] Computing correlations...")

    corr_data = []
    annot_data = []
    for p in PARAMS:
        row = {}
        annot_row = {}
        for k in KPIS:
            pearson_r, pearson_p = stats.pearsonr(df[p], df[k])
            spearman_r, spearman_p = stats.spearmanr(df[p], df[k])
            row[k] = spearman_r
            sig = "***" if spearman_p < 0.001 else "**" if spearman_p < 0.01 else "*" if spearman_p < 0.05 else ""
            annot_row[k] = f"{spearman_r:+.3f}{sig}"
            print(f"  {PARAM_LABELS[p]:30s} → {KPI_LABELS[k]:25s}  "
                  f"Spearman r={spearman_r:+.3f}  Pearson r={pearson_r:+.3f}  {sig}")
        corr_data.append(row)
        annot_data.append(annot_row)

    corr_df = pd.DataFrame(corr_data, index=[PARAM_LABELS[p] for p in PARAMS])
    corr_df.columns = [KPI_LABELS[k] for k in KPIS]

    annot_df = pd.DataFrame(annot_data, index=[PARAM_LABELS[p] for p in PARAMS])
    annot_df.columns = [KPI_LABELS[k] for k in KPIS]

    fig, ax = plt.subplots(figsize=(10, 4))
    sns.heatmap(
        corr_df, annot=annot_df, fmt="", cmap="RdBu_r",
        center=0, vmin=-1, vmax=1, linewidths=0.5,
        ax=ax, cbar_kws={"label": "Spearman correlation"},
        annot_kws={"size": 10}
    )
    ax.set_title("Parameter → KPI Spearman Correlation\n(* p<0.05  ** p<0.01  *** p<0.001)",
                 fontsize=12, pad=12)
    plt.tight_layout()
    path = os.path.join(output_dir, "1_correlation_matrix.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")

# ── 2. FEATURE IMPORTANCE ─────────────────────────────────────────────────────

def plot_feature_importance(df, output_dir):
    print("\n[2/4] Computing Random Forest feature importance...")

    X = df[PARAMS].values
    fig, axes = plt.subplots(1, len(KPIS), figsize=(16, 4))

    for ax, kpi in zip(axes, KPIS):
        y = df[kpi].values
        rf = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
        rf.fit(X, y)
        importances = rf.feature_importances_
        indices = np.argsort(importances)[::-1]

        colors = ["#534AB7" if i == indices[0] else "#AFA9EC" for i in range(len(PARAMS))]
        bars = ax.barh(
            [PARAM_LABELS[PARAMS[i]] for i in indices[::-1]],
            importances[indices[::-1]],
            color=colors[::-1], edgecolor="none", height=0.6
        )
        ax.set_xlabel("Importance")
        ax.set_title(KPI_LABELS[kpi], fontsize=11)
        ax.set_xlim(0, max(importances) * 1.2)
        for bar, imp in zip(bars, importances[indices[::-1]]):
            ax.text(imp + 0.005, bar.get_y() + bar.get_height()/2,
                    f"{imp:.3f}", va="center", fontsize=9)
        score = rf.score(X, y)
        ax.text(0.98, 0.02, f"R²={score:.3f}", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=9, color="gray")

        print(f"  {KPI_LABELS[kpi]:25s}  R²={score:.3f}  "
              f"top={PARAM_LABELS[PARAMS[indices[0]]]} ({importances[indices[0]]:.3f})")

    fig.suptitle("Random Forest Feature Importance per KPI", fontsize=13, y=1.02)
    plt.tight_layout()
    path = os.path.join(output_dir, "2_feature_importance.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")

# ── 3. SCATTER PLOTS (param vs KPI) ──────────────────────────────────────────

def plot_scatter(df, output_dir):
    print("\n[3/4] Plotting parameter vs KPI scatter plots...")

    fig, axes = plt.subplots(len(KPIS), len(PARAMS),
                              figsize=(4 * len(PARAMS), 3.5 * len(KPIS)))

    for row_idx, kpi in enumerate(KPIS):
        for col_idx, param in enumerate(PARAMS):
            ax = axes[row_idx][col_idx]
            x = df[param].values
            y = df[kpi].values

            # scatter with density color
            ax.scatter(x, y, alpha=0.3, s=8, color="#378ADD")

            # trend line
            z = np.polyfit(x, y, 1)
            p = np.poly1d(z)
            x_line = np.linspace(x.min(), x.max(), 100)
            ax.plot(x_line, p(x_line), color="#E24B4A", linewidth=1.5)

            r, pval = stats.spearmanr(x, y)
            ax.set_title(f"r={r:+.3f}", fontsize=9,
                         color="#E24B4A" if abs(r) > 0.5 else "gray")

            if row_idx == len(KPIS) - 1:
                ax.set_xlabel(PARAM_LABELS[param], fontsize=9)
            if col_idx == 0:
                ax.set_ylabel(KPI_LABELS[kpi], fontsize=9)
            ax.tick_params(labelsize=8)

    fig.suptitle("Parameter vs KPI — Spearman r shown (red = strong correlation)",
                 fontsize=12, y=1.01)
    plt.tight_layout()
    path = os.path.join(output_dir, "3_scatter_plots.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")

# ── 4. PARTIAL DEPENDENCE PLOTS ───────────────────────────────────────────────

def plot_partial_dependence(df, output_dir):
    print("\n[4/4] Computing partial dependence plots...")

    X = df[PARAMS].values
    fig, axes = plt.subplots(len(KPIS), len(PARAMS),
                              figsize=(4 * len(PARAMS), 3.5 * len(KPIS)))

    for row_idx, kpi in enumerate(KPIS):
        y = df[kpi].values
        rf = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
        rf.fit(X, y)

        for col_idx, param in enumerate(PARAMS):
            ax = axes[row_idx][col_idx]
            param_vals = np.linspace(df[param].min(), df[param].max(), 50)
            X_mean = np.tile(X.mean(axis=0), (50, 1))
            X_mean[:, col_idx] = param_vals
            y_pred = rf.predict(X_mean)

            ax.plot(param_vals, y_pred, color="#534AB7", linewidth=2)
            ax.fill_between(param_vals, y_pred, alpha=0.15, color="#534AB7")
            if kpi != "mean_rssi_dbm":
                ax.set_ylim(bottom=0)

            if row_idx == len(KPIS) - 1:
                ax.set_xlabel(PARAM_LABELS[param], fontsize=9)
            if col_idx == 0:
                ax.set_ylabel(KPI_LABELS[kpi], fontsize=9)
            ax.tick_params(labelsize=8)

        print(f"  Done: {KPI_LABELS[kpi]}")

    fig.suptitle("Partial Dependence — effect of each parameter on KPI\n"
                 "(all other parameters held at their mean)",
                 fontsize=12, y=1.01)
    plt.tight_layout()
    path = os.path.join(output_dir, "4_partial_dependence.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")

# ── 5. SUMMARY REPORT ─────────────────────────────────────────────────────────

def print_summary(df, output_dir):
    print("\n" + "="*60)
    print("SUMMARY — most influential parameters per KPI")
    print("="*60)

    for kpi in KPIS:
        y = df[kpi].values
        corrs = {}
        for p in PARAMS:
            r, _ = stats.spearmanr(df[p].values, y)
            corrs[p] = abs(r)
        ranked = sorted(corrs.items(), key=lambda x: x[1], reverse=True)
        print(f"\n  {KPI_LABELS[kpi]}")
        for p, r in ranked:
            bar = "█" * int(r * 20)
            print(f"    {PARAM_LABELS[p]:30s}  |{bar:<20}|  r={r:.3f}")

    print("\n  Recommendation for next round:")
    print("  → Focus on parameters with |r| > 0.5 — widen their range")
    print("  → Parameters with |r| < 0.1 — reduce their combinations")
    print("="*60)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset.csv")
    parser.add_argument("--output",  default="dataset-analysis")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    df = load(args.dataset)

    plot_correlation(df, args.output)
    plot_feature_importance(df, args.output)
    plot_scatter(df, args.output)
    plot_partial_dependence(df, args.output)
    print_summary(df, args.output)

    print(f"\nAll plots saved to: {args.output}/")


if __name__ == "__main__":
    main()