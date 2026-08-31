#!/usr/bin/env python3
# =============================================================================
# plot_time_evolution.py
# Splits a serial.log into fixed-duration windows and plots how metrics
# evolve across windows — useful for deciding the minimum simulation duration.
#
# Metrics computed per window:
#   - Loss rate (%)
#   - Mean end-to-end delay (s)
#   - Throughput (bytes/s/node)
#   - Mean RSSI (dBm)
#
# Usage:
#   python3 tools/plot_time_evolution.py \
#       --log results/sim_35/cooja/serial.log \
#       --window 600 \
#       --nodes 10 \
#       --output results/sim_35/cooja/time_evolution.png
# =============================================================================

import argparse
import glob
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from sender_roles import get_main_senders


MSG_SIZE_BYTES = 8  # payload bytes per packet


# ── OML (FIT IoT-Lab radio monitoring) ─────────────────────────────────────────

def parse_oml_rssi(oml_dir):
    """
    Read m3_*.oml radio-sniffer files (absolute unix timestamps + rssi column).
    serial.log receive lines on FIT IoT-Lab carry no rssi= field — RSSI only
    exists in these per-node OML streams, so the windowed RSSI panel needs
    them as a separate source.
    Returns a flat list of (timestamp, rssi) tuples across all nodes.
    """
    samples = []
    if not oml_dir or not os.path.isdir(oml_dir):
        return samples

    for path in glob.glob(os.path.join(oml_dir, 'm3_*.oml')):
        radio_schema = None
        ts_s_col = ts_us_col = rssi_col = None
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('schema:'):
                    parts = line.split()
                    if len(parts) >= 3 and 'radio' in parts[2]:
                        radio_schema = parts[1]
                        fields = [p.split(':')[0] for p in parts[3:]]
                        if 'rssi' in fields:
                            rssi_col = fields.index('rssi')
                            ts_s_col = fields.index('timestamp_s')
                            ts_us_col = fields.index('timestamp_us')
                    continue
                if radio_schema is None or rssi_col is None:
                    continue
                parts = line.split()
                if len(parts) < 4 or parts[1] != radio_schema:
                    continue
                values = parts[3:]
                try:
                    ts = int(values[ts_s_col]) + int(values[ts_us_col]) / 1e6
                    rssi = float(values[rssi_col])
                except (ValueError, IndexError):
                    continue
                samples.append((ts, rssi))

    return samples


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_log(path):
    """
    Single-pass parse.  Returns:
        events  : list of dicts {type, t, node, key, rssi}
                  type = 's' | 'r'
    """
    events = []
    line_re = re.compile(r'^([\d.]+);([^;]+);(.+)$')

    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            m = line_re.match(line)
            if not m:
                continue
            t_str, node, rest = m.group(1), m.group(2), m.group(3)
            try:
                t = float(t_str)
            except ValueError:
                continue

            parts = rest.split()
            if not parts or parts[0] not in ('s', 'r'):
                continue

            ev_type = parts[0]
            if len(parts) < 3:
                continue

            ipv6, seq = parts[1], parts[2]
            suffix = ipv6[-4:]
            key = suffix + seq

            rssi = None
            if ev_type == 'r':
                rm = re.search(r'rssi=(-?\d+)', rest)
                if rm:
                    rssi = int(rm.group(1))

            events.append({'type': ev_type, 't': t, 'node': node,
                           'key': key, 'rssi': rssi, 'ipv6': ipv6})

    return events


# ── Windowed metrics ──────────────────────────────────────────────────────────

def compute_windows(events, window_sec, nb_nodes, oml_samples=None):
    """
    Assign each packet to the window in which it was SENT.
    Receive events (even if they land in a later window) are matched
    back to the send event's window for delay computation.

    Each send is consumed exactly once (FIFO per key) so that sequence-number
    wrap-arounds don't cause a later-cycle receive to be misattributed to a
    recycled key from an earlier cycle, which would inflate recv > sent.

    Returns list of dicts, one per window, ordered by window index.
    """
    if not events:
        return []

    from collections import deque

    t_start = events[0]['t']

    # First pass: build per-key FIFO queues of (send_time, window_index, node)
    # so that each receive consumes the earliest matching send (handles seq reuse).
    send_queues         = defaultdict(deque)   # key → deque[(send_t, win, node)]
    ipv6_suffix_to_node = {}

    for ev in events:
        if ev['type'] == 's':
            win = int((ev['t'] - t_start) / window_sec)
            send_queues[ev['key']].append((ev['t'], win, ev['node']))
            ipv6_suffix_to_node[ev['ipv6'][-4:]] = ev['node']

    # Determine total number of windows
    t_end  = events[-1]['t']
    n_wins = int((t_end - t_start) / window_sec) + 1

    # Bin OML RSSI samples (absolute timestamps) onto the same window grid
    oml_rssi_vals = defaultdict(list)
    for ts, rssi in (oml_samples or []):
        win = int((ts - t_start) / window_sec)
        if 0 <= win < n_wins:
            oml_rssi_vals[win].append(rssi)

    # Per-window accumulators
    sent       = defaultdict(int)
    recv       = defaultdict(int)
    delay_sums = defaultdict(float)
    delay_cnts = defaultdict(int)
    rssi_vals  = defaultdict(list)

    # Per-window per-node sent/recv for per-node loss std
    node_sent = defaultdict(lambda: defaultdict(int))  # win → node → count
    node_recv = defaultdict(lambda: defaultdict(int))

    # Count sends (consume a copy — keep originals for receive matching below)
    for key, dq in send_queues.items():
        for s_t, win, node in dq:
            sent[win] += 1
            node_sent[win][node] += 1

    # Make fresh queues for receive matching (send_queues consumed above)
    match_queues = defaultdict(deque)
    for key, dq in send_queues.items():
        match_queues[key] = deque(dq)   # shallow copy of the deque

    for ev in events:
        if ev['type'] == 'r':
            key = ev['key']
            if not match_queues[key]:
                continue  # no unmatched send for this key — skip
            # Consume the earliest matching send (FIFO)
            s_t, win, sender_node = match_queues[key].popleft()
            recv[win] += 1
            if sender_node:
                node_recv[win][sender_node] += 1

            # Delay
            r_t = ev['t']
            if r_t >= s_t:
                delay_sums[win] += (r_t - s_t)
                delay_cnts[win] += 1

            # RSSI
            if ev['rssi'] is not None:
                rssi_vals[win].append(ev['rssi'])

    results = []
    for win in range(n_wins):
        t_win_start = t_start + win * window_sec
        t_win_end   = t_win_start + window_sec
        n_sent = sent[win]
        n_recv = recv[win]
        n_lost = n_sent - n_recv

        loss_rate  = (n_lost / n_sent * 100) if n_sent else float('nan')
        mean_delay = (delay_sums[win] / delay_cnts[win]) if delay_cnts[win] else float('nan')
        throughput = ((n_recv * MSG_SIZE_BYTES) / window_sec / nb_nodes) if n_recv else 0.0
        # OML radio monitoring takes priority — FIT IoT-Lab receive lines carry no rssi= field
        if oml_rssi_vals[win]:
            mean_rssi = sum(oml_rssi_vals[win]) / len(oml_rssi_vals[win])
        elif rssi_vals[win]:
            mean_rssi = sum(rssi_vals[win]) / len(rssi_vals[win])
        else:
            mean_rssi = float('nan')

        results.append({
            'window':      win,
            't_start':     t_win_start,
            't_end':       t_win_end,
            'label':       f"{int((t_win_start - t_start)/60)}-{int((t_win_end - t_start)/60)} min",
            'n_sent':      n_sent,
            'n_recv':      n_recv,
            'loss_rate':   loss_rate,
            'mean_delay':  mean_delay,
            'throughput':  throughput,
            'mean_rssi':   mean_rssi,
        })

    return results


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_windows(windows, out_path, window_sec, sim_label=""):
    n = len(windows)
    labels = [w['label'] for w in windows]
    x = list(range(n))

    loss       = [w['loss_rate']  for w in windows]
    delay      = [w['mean_delay'] for w in windows]
    throughput = [w['throughput'] for w in windows]
    rssi       = [w['mean_rssi']  for w in windows]

    # Replace NaN with None for matplotlib gap handling
    def nan_to_none(lst):
        import math
        return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in lst]

    loss_p       = nan_to_none(loss)
    delay_p      = nan_to_none(delay)
    throughput_p = nan_to_none(throughput)
    rssi_p       = nan_to_none(rssi)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(
        f"Metric Evolution per {int(window_sec/60)}-Minute Window"
        + (f"  —  {sim_label}" if sim_label else ""),
        fontsize=14, fontweight='bold'
    )

    def _bar_with_line(ax, vals, color, ylabel, title):
        """Bar chart + connecting line; highlight windows where value differs
        significantly from the mean (flag potential warm-up artefacts)."""
        import math
        valid = [v for v in vals if v is not None]
        if valid:
            grand_mean = sum(valid) / len(valid)
            ax.axhline(grand_mean, color='gray', linestyle='--', linewidth=1,
                       label=f"mean = {grand_mean:.3g}")
        bar_colors = []
        for v in vals:
            if v is None or (valid and abs(v - grand_mean) > 0.2 * abs(grand_mean) + 1e-9):
                bar_colors.append('#f4a460')   # warm colour for outliers
            else:
                bar_colors.append(color)

        ax.bar(x, [v if v is not None else 0 for v in vals],
               color=bar_colors, alpha=0.75, zorder=2)
        # Line connecting non-None points
        x_line = [xi for xi, v in zip(x, vals) if v is not None]
        y_line = [v  for v in vals         if v is not None]
        if len(x_line) > 1:
            ax.plot(x_line, y_line, 'o-', color='black', linewidth=1.5,
                    markersize=5, zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=8)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.grid(axis='y', linestyle=':', alpha=0.5)

    _bar_with_line(axes[0, 0], loss_p,       '#2196F3', 'Loss rate (%)',         'Packet Loss Rate')
    _bar_with_line(axes[0, 1], delay_p,      '#4CAF50', 'Mean delay (s)',        'End-to-End Delay')
    _bar_with_line(axes[1, 0], throughput_p, '#FF5722', 'Throughput (B/s/node)', 'Throughput')
    _bar_with_line(axes[1, 1], rssi_p,       '#9C27B0', 'Mean RSSI (dBm)',       'Mean RSSI')

    # Packet count annotation on the loss chart
    for xi, w in zip(x, windows):
        axes[0, 0].annotate(
            f"s:{w['n_sent']}\nr:{w['n_recv']}",
            xy=(xi, 0), xytext=(xi, -0.05),
            textcoords=('data', 'axes fraction'),
            ha='center', va='top', fontsize=6, color='#555555'
        )

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"  ✓ Plot saved → {out_path}")
    return fig


# ── Table print ───────────────────────────────────────────────────────────────

def print_table(windows):
    header = f"{'Window':<14} {'Sent':>6} {'Recv':>6} {'Loss%':>7} {'Delay(s)':>10} {'Tput B/s/n':>12} {'RSSI dBm':>10}"
    print(header)
    print('-' * len(header))
    import math
    for w in windows:
        loss  = f"{w['loss_rate']:.2f}"  if not math.isnan(w['loss_rate'])  else "  n/a"
        delay = f"{w['mean_delay']:.4f}" if not math.isnan(w['mean_delay']) else "    n/a"
        rssi  = f"{w['mean_rssi']:.1f}"  if not math.isnan(w['mean_rssi'])  else "   n/a"
        print(f"{w['label']:<14} {w['n_sent']:>6} {w['n_recv']:>6} {loss:>7} {delay:>10} {w['throughput']:>12.3f} {rssi:>10}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Plot metric evolution across fixed-duration windows of a serial.log"
    )
    ap.add_argument('--log',    required=True, help='Path to serial.log')
    ap.add_argument('--window', type=int, default=600,
                    help='Window size in seconds (default: 600 = 10 min)')
    ap.add_argument('--nodes',  type=int, default=10,
                    help='Number of sender nodes (for throughput normalisation)')
    ap.add_argument('--output', default=None,
                    help='Output PNG path (default: same dir as log)')
    ap.add_argument('--oml-dir', default=None,
                    help='Directory with m3_N.oml radio-monitoring files (FIT IoT-Lab RSSI). '
                         'Default: same directory as --log')
    ap.add_argument('--senders', default=None,
                    help='Comma-separated sender node IDs to restrict metrics to, '
                         'e.g. "216,218,226,227,228". Overrides auto-detection. '
                         'Useful when the log mixes main senders with interferer traffic.')
    ap.add_argument('--no-auto-detect-main', action='store_true',
                    help='Disable automatic main-vs-interferer sender detection '
                         '(see tools/sender_roles.py) and include every sender node. '
                         'Ignored if --senders is given.')
    ap.add_argument('--start-frac', type=float, default=0.05,
                    help='Auto-detection heuristic: a node must send within this '
                         'fraction of the experiment span from the start to count '
                         'as a main sender (default: %(default)s)')
    ap.add_argument('--end-frac', type=float, default=0.05,
                    help='Auto-detection heuristic: a node must send within this '
                         'fraction of the experiment span from the end to count '
                         'as a main sender (default: %(default)s)')
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print(f"✗ File not found: {args.log}")
        sys.exit(1)

    out_path = args.output or os.path.join(
        os.path.dirname(args.log),
        f"time_evolution_w{args.window}s.png"
    )

    print(f"→ Parsing: {args.log}")
    events = parse_log(args.log)

    if args.senders:
        allowed = {n.strip() if n.strip().startswith('m3-') else f"m3-{n.strip()}"
                   for n in args.senders.split(',')}
        sim_label_suffix = f" (senders: {sorted(allowed)})"
    elif not args.no_auto_detect_main:
        send_events = [(e['t'], e['node']) for e in events if e['type'] == 's']
        allowed, source = get_main_senders(args.log, send_events=send_events,
                                            start_frac=args.start_frac, end_frac=args.end_frac)
        if allowed:
            print(f"  Auto-detected main senders [{source}]: {sorted(allowed)}")
            sim_label_suffix = f" (senders: {sorted(allowed)})"
        else:
            print("  Auto-detection inconclusive — using all senders")
            sim_label_suffix = ""
    else:
        allowed = None
        sim_label_suffix = ""

    if allowed:
        # Only filter sends — receives are matched back to a send by key, so
        # dropping non-allowed sends automatically excludes their receives too.
        events = [e for e in events if e['type'] != 's' or e['node'] in allowed]

    sim_label = os.path.basename(os.path.dirname(os.path.dirname(args.log))) + sim_label_suffix

    print(f"  {sum(1 for e in events if e['type']=='s')} send events, "
          f"{sum(1 for e in events if e['type']=='r')} receive events")
    print(f"  Time range: {events[0]['t']:.1f}s – {events[-1]['t']:.1f}s "
          f"({(events[-1]['t']-events[0]['t'])/60:.1f} min)")

    oml_dir = args.oml_dir or os.path.dirname(args.log)
    oml_samples = parse_oml_rssi(oml_dir)
    if oml_samples:
        print(f"  {len(oml_samples)} OML RSSI sample(s) from {oml_dir}")

    windows = compute_windows(events, args.window, args.nodes, oml_samples=oml_samples)
    print(f"\n  {len(windows)} window(s) of {args.window}s ({args.window//60} min) each\n")
    print_table(windows)

    plot_windows(windows, out_path, args.window, sim_label)


if __name__ == '__main__':
    main()
