#!/usr/bin/env python3
"""
tools/kpi_extractor.py
Sliding-window KPI extraction from a serial.log file.
Yields (kpi_dict, window_start_s, window_end_s) for each window.
"""

import bisect
import glob
import math
import os
import time
from collections import defaultdict

from sender_roles import get_main_senders

MSG_SIZE_DEFAULT = 8


def _parse_oml(oml_path):
    """Return list of (timestamp_s, rssi_dbm) from a FIT IoT-LAB OML file."""
    samples      = []
    radio_schema = None
    rssi_col     = None
    with open(oml_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('schema:'):
                parts = line.split()
                if len(parts) >= 3 and ('radio_sniffer' in parts[2] or 'radio' in parts[2]):
                    radio_schema = parts[1]
                    fields = [p.split(':')[0] for p in parts[3:]]
                    if 'rssi' in fields:
                        rssi_col = fields.index('rssi')
                continue
            if radio_schema is None or rssi_col is None:
                continue
            parts = line.split()
            if len(parts) < 4 or parts[1] != radio_schema:
                continue
            idx = 3 + rssi_col
            if idx < len(parts):
                try:
                    samples.append((float(parts[0]), float(parts[idx])))
                except ValueError:
                    pass
    return samples


def _load_oml_rssi(oml_dir):
    flat = []
    for path in sorted(glob.glob(os.path.join(oml_dir, '*m3_*.oml'))):
        flat.extend(_parse_oml(path))
    flat.sort(key=lambda x: x[0])
    # Normalize: make timestamps relative to first sample
    if flat:
        t0 = flat[0][0]
        flat = [(ts - t0, rssi) for ts, rssi in flat]
    return flat

def load_log(log_path):
    sends     = {}   # (node, seq) -> ts
    receives  = {}   # (ip, seq)   -> ts
    events    = []
    exp_start = exp_end = None

    with open(log_path, buffering=1 << 20) as f:
        for line in f:
            parts = line.split(";", 2)
            if len(parts) != 3:
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                continue
            node   = parts[1]
            tokens = parts[2].split()
            if len(tokens) < 3:
                continue
            kind, ip, seq = tokens[0], tokens[1], tokens[2]
            if kind not in ("s", "r"):
                continue

            if exp_start is None:
                exp_start = ts
            exp_end = ts

            if kind == "s":
                sends[(node, seq)] = ts
                events.append((ts, node, "s", ip, seq))
            else:
                receives[(ip, seq)] = ts
                events.append((ts, node, "r", ip, seq))

    # log is written in timestamp order — no sort needed
    return sends, receives, events, exp_start, exp_end


def _ip_suffix(ip):
    """Return the last colon-delimited segment of an IPv6 address.
    This normalizes fe80::XXXX and fd00::XXXX to the same key XXXX,
    fixing mismatches when sends use link-local and receives use global addresses.
    """
    return ip.rpartition(":")[2] if ip else ip


def compute_window_kpis(window_events, window_start_abs, window_end_abs,
                         n_nodes, msg_size=MSG_SIZE_DEFAULT, rssi_samples=None):
    duration = window_end_abs - window_start_abs
    if duration <= 0:
        return None

    # Key: (ip_suffix, seq) — normalized to last IPv6 segment so that
    # fe80::XXXX (send, link-local) matches fd00::XXXX (receive, global unicast).
    send_ts    = {}   # (ip_suffix, seq) -> ts
    recv_ts    = {}   # (ip_suffix, seq) -> ts
    ip_to_node = {}   # ip_suffix -> node label (built from send events)
    node_sent  = defaultdict(int)

    for ts, node, kind, ip, seq in window_events:
        ip_k = _ip_suffix(ip)
        if kind == "s":
            send_ts[(ip_k, seq)] = ts
            ip_to_node[ip_k] = node
            node_sent[node] += 1
        elif kind == "r":
            if (ip_k, seq) in send_ts:   # only match if send already seen — consistent with run_analysis
                recv_ts[(ip_k, seq)] = ts

    n_sent = len(send_ts)
    if n_sent == 0:
        return None

    # Matched packets: receives that had a prior send (single-pass, timestamp-ordered)
    matched_keys = recv_ts.keys()
    n_matched    = len(matched_keys)

    loss_rate_pct = 100.0 * (1.0 - n_matched / n_sent)

    # Denominator is the number of nodes that actually sent in this window,
    # not the caller-supplied total node count — a topology with idle/relay
    # nodes would otherwise dilute throughput and disagree with run_analysis.py,
    # which normalizes by active senders during training data generation.
    active_senders   = len(set(ip_to_node.values())) or n_nodes
    throughput_pkt_s = ((n_matched * msg_size) / duration) / active_senders

    # Delay: only reject negative values — no upper cap (matches run_analysis)
    delays = [recv_ts[k] - send_ts[k] for k in matched_keys
              if recv_ts[k] - send_ts[k] >= 0]

    mean_delay = sum(delays) / len(delays) if delays else 0.0
    std_delay  = math.sqrt(
        sum((d - mean_delay) ** 2 for d in delays) / len(delays)
    ) if len(delays) > 1 else 0.0

    # Per-node PRR: node_sent already counted in the main loop above
    node_recv = defaultdict(int)
    for (ip_k, seq) in matched_keys:
        node = ip_to_node.get(ip_k)
        if node:
            node_recv[node] += 1

    per_node_prr = [
        node_recv.get(n, 0) / ns
        for n, ns in node_sent.items() if ns > 0
    ]
    per_node_min_prr = min(per_node_prr) if per_node_prr else 0.0

    per_node_loss = [100.0 * (1.0 - p) for p in per_node_prr]
    mean_loss_node = sum(per_node_loss) / len(per_node_loss) if per_node_loss else 0.0
    std_loss_rate  = math.sqrt(
        sum((l - mean_loss_node) ** 2 for l in per_node_loss) / len(per_node_loss)
    ) if len(per_node_loss) > 1 else 0.0

    if rssi_samples:
        rssi_mean = sum(rssi_samples) / len(rssi_samples)
        rssi_std  = math.sqrt(
            sum((r - rssi_mean) ** 2 for r in rssi_samples) / len(rssi_samples)
        ) if len(rssi_samples) > 1 else 0.0
        rssi_min  = min(rssi_samples)
    else:
        rssi_mean = -75.0
        rssi_std  = 10.0
        rssi_min  = -91.0

    # Interaction terms (must match training notebook)
    rssi_x_loss         = rssi_mean * loss_rate_pct
    throughput_per_loss = throughput_pkt_s / (loss_rate_pct + 1e-6)

    return {
        "mean_rssi_dbm":       rssi_mean,
        "std_rssi_dbm":        rssi_std,
        "min_rssi_dbm":        rssi_min,
        "loss_rate_pct":       loss_rate_pct,
        "throughput_pkt_s":    throughput_pkt_s,
        "mean_delay_s":        mean_delay,
        "std_delay_s":         std_delay,
        "std_loss_rate":       std_loss_rate,
        "per_node_min_prr":    per_node_min_prr,
        "rssi_x_loss":         rssi_x_loss,
        "throughput_per_loss": throughput_per_loss,
    }


def extract_kpis(log_path, window_s=30, step_s=10,
                 n_nodes=20, msg_size=MSG_SIZE_DEFAULT,
                 realtime=False, speed=1.0, live=False,
                 senders=None, auto_detect_main=True,
                 start_frac=0.05, end_frac=0.05):
    """Generator — yields (kpi_dict, w_start_s, w_end_s).

    live=True  : tail the file as it is written (real deployment).
                 Ignores realtime/speed — windows are gated by log timestamps.
    live=False : load the whole log upfront and replay (default).
                 realtime+speed throttle delivery for demo purposes.

    senders          : explicit set/comma-string of node labels (e.g.
                        "218,216,226,228,227" or "m3-218,m3-216,...") to
                        restrict KPI computation to. Overrides auto-detection.
    auto_detect_main : when `senders` is not given, try to automatically
                        figure out which nodes are the main flow of interest
                        (vs. interferers/background traffic) via
                        sender_roles.get_main_senders — see that module for
                        the metadata/heuristic detection logic. Set to False
                        to fall back to including every sender node.
    """
    if live:
        yield from _extract_kpis_live(log_path, window_s, step_s, n_nodes, msg_size,
                                       senders=senders, auto_detect_main=auto_detect_main)
        return

    print(f"  Loading log: {log_path}")
    sends, receives, events, exp_start, exp_end = load_log(log_path)
    exp_duration = exp_end - exp_start
    print(f"  {len(events)} events  |  duration={exp_duration:.0f}s  |  "
          f"{len(sends)} sends  {len(receives)} receives")

    allowed = None
    if senders:
        raw = ",".join(senders) if not isinstance(senders, str) else senders
        allowed = {n.strip() if n.strip().startswith("m3-") else f"m3-{n.strip()}"
                   for n in raw.split(',') if n.strip()}
        print(f"  Restricting to manually-specified senders: {sorted(allowed)}")
    elif auto_detect_main:
        send_events = [(ts, node) for ts, node, kind, ip, seq in events if kind == 's']
        allowed, source = get_main_senders(log_path, send_events=send_events,
                                            start_frac=start_frac, end_frac=end_frac)
        if allowed:
            print(f"  Auto-detected main senders [{source}]: {sorted(allowed)}")
        else:
            print("  Auto-detection inconclusive — using all senders")

    if allowed:
        events = [e for e in events if e[2] != 's' or e[1] in allowed]

    # Load OML timestamped RSSI samples from the same directory as the log
    oml_dir     = os.path.dirname(os.path.abspath(log_path))
    oml_samples = _load_oml_rssi(oml_dir)   # [(ts, rssi), ...] sorted by ts
    if oml_samples:
        print(f"  OML RSSI: {len(oml_samples)} samples — will use per-window stats")
    else:
        print("  OML RSSI: not found — using fallback placeholder values")

    # Pre-extract timestamps once for O(log n) bisect slicing per window
    event_times = [e[0] for e in events]
    oml_times   = [ts for ts, _ in oml_samples]

    w_offset = 0.0
    while w_offset + window_s <= exp_duration:
        w_start_abs = exp_start + w_offset
        w_end_abs   = exp_start + w_offset + window_s

        lo = bisect.bisect_left(event_times, w_start_abs)
        hi = bisect.bisect_left(event_times, w_end_abs)
        window_events = events[lo:hi]

        # Filter OML samples whose timestamp falls inside this window
        olo = bisect.bisect_left(oml_times, w_offset)
        ohi = bisect.bisect_left(oml_times, w_offset + window_s)
        window_rssi = [oml_samples[i][1] for i in range(olo, ohi)]

        kpis = compute_window_kpis(
            window_events, w_start_abs, w_end_abs, n_nodes, msg_size,
            rssi_samples=window_rssi if window_rssi else None)

        if kpis is not None:
            yield kpis, w_offset, w_offset + window_s

        w_offset += step_s
        if realtime and speed > 0:
            time.sleep(step_s / speed)


def _extract_kpis_live(log_path, window_s, step_s, n_nodes, msg_size,
                        senders=None, auto_detect_main=True):
    """Tail log_path in real-time and yield windows as events accumulate.

    Blocks on readline() + 50 ms poll — never terminates unless interrupted.
    OML RSSI is not tailed (falls back to placeholder values).

    senders: explicit comma-string/set of node labels to keep — same format
             as extract_kpis(). The temporal heuristic in sender_roles needs
             the full experiment span up front, which isn't available while
             tailing, so live mode only honors an explicit `senders` list or
             an experiment_info.txt metadata file (checked once at start).
    """
    print(f"  Live-tail mode: {log_path}")

    allowed = None
    if senders:
        raw = ",".join(senders) if not isinstance(senders, str) else senders
        allowed = {n.strip() if n.strip().startswith("m3-") else f"m3-{n.strip()}"
                   for n in raw.split(',') if n.strip()}
        print(f"  Restricting to manually-specified senders: {sorted(allowed)}")
    elif auto_detect_main:
        allowed, source = get_main_senders(log_path, send_events=None)
        if allowed:
            print(f"  Auto-detected main senders [{source}]: {sorted(allowed)}")
        else:
            print("  No experiment_info.txt found — using all senders "
                  "(live mode can't run the temporal heuristic)")

    buffer    = []      # [(ts, node, kind, ip, seq), ...]
    w_start   = None    # absolute timestamp of current window start
    exp_start = None    # absolute timestamp of the very first event

    with open(log_path) as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05)
                continue

            parts = line.strip().split(";")
            if len(parts) != 3:
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                continue
            node, msg = parts[1], parts[2]
            tokens = msg.split()
            if len(tokens) < 3 or tokens[0] not in ("s", "r"):
                continue
            kind, ip, seq = tokens[0], tokens[1], tokens[2]

            if kind == "s" and allowed and node not in allowed:
                continue

            if exp_start is None:
                exp_start = ts
                w_start   = ts
                print(f"  Live first event at t={ts:.3f}s")

            buffer.append((ts, node, kind, ip, seq))

            # Yield every completed window and advance by step_s
            while ts - w_start >= window_s:
                w_end    = w_start + window_s
                w_events = [e for e in buffer if w_start <= e[0] < w_end]
                kpis = compute_window_kpis(
                    w_events, w_start, w_end, n_nodes, msg_size,
                    rssi_samples=None)
                if kpis is not None:
                    yield kpis, w_start - exp_start, w_start - exp_start + window_s
                w_start += step_s
                # Drop events that are before the new window start
                buffer = [e for e in buffer if e[0] >= w_start]
