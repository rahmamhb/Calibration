#!/usr/bin/env python3
"""
tools/sender_roles.py
Figures out which sender nodes in a serial.log are the "main" flow of
interest, vs. interferers/background traffic — without hardcoding node IDs,
so the same KPI tools work on any experiment.

Two detection paths, tried in order:
  1. metadata  — an experiment_info.txt next to the log with a
                 "Main senders : m3-A,B,C" line. Authoritative when present.
  2. heuristic — per-node first/last send time relative to the experiment's
                 full time span. Phase-based interference experiments only
                 switch interferers on for a sub-interval, so a node that is
                 NOT active near both the very start and the very end of the
                 run is classified as an interferer. A node active across
                 the whole span is "main".

If neither path can tell nodes apart (e.g. every node is active the whole
time — a normal multi-flow experiment with no interferers), detection
reports "none" and callers should fall back to including every node.
"""

import glob
import os
import re


def _normalize_node_list(raw, prefix="m3-"):
    """'m3-218,216,226' -> {'m3-218','m3-216','m3-226'}.
    experiment_info.txt only carries the prefix on the first item."""
    nodes = set()
    for tok in raw.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if not tok.startswith(prefix):
            tok = prefix + tok
        nodes.add(tok)
    return nodes


def find_experiment_file(log_path, glob_pattern, max_levels=3):
    """Search the log's directory, then up to `max_levels` parents, for a
    file matching `glob_pattern` (e.g. '*experiment_info*.txt'). Experiments
    of this shape are laid out as:
        results/ScenarioNN/experiment_info.txt
        results/ScenarioNN/node_positions.json
        results/ScenarioNN/main/serial.log
    so the file typically sits one directory above the log itself."""
    d = os.path.dirname(os.path.abspath(log_path)) or "."
    for _ in range(max_levels):
        matches = glob.glob(os.path.join(d, glob_pattern))
        if matches:
            return matches[0]
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def find_experiment_info(log_path):

    return find_experiment_file(log_path, '*experiment_info*.txt')


def find_node_positions(log_path):
    
    return find_experiment_file(log_path, 'node_positions.json')


def parse_main_senders_from_info(info_path):
    """Parse a 'Main senders : m3-218,216,226,228,227' line. None if absent."""
    line_re = re.compile(r'^\s*Main senders\s*:\s*(.+)$', re.IGNORECASE)
    with open(info_path) as f:
        for line in f:
            m = line_re.match(line)
            if m:
                return _normalize_node_list(m.group(1))
    return None


def detect_main_senders_heuristic(send_events, start_frac=0.05, end_frac=0.05):
    """
    send_events: iterable of (timestamp, node_label) for 's' events only.

    A node is "main" if its first send lands within `start_frac` of the
    experiment span from the start AND its last send lands within
    `end_frac` of the span from the end — i.e. it ran continuously,
    unlike an interferer that is only switched on for a phase sub-interval.

    Returns None if there's nothing to distinguish (no events). Returns the
    full set of nodes if every node looks the same (no filtering needed).
    """
    first, last = {}, {}
    t_min = t_max = None
    for ts, node in send_events:
        if t_min is None or ts < t_min:
            t_min = ts
        if t_max is None or ts > t_max:
            t_max = ts
        if node not in first or ts < first[node]:
            first[node] = ts
        if node not in last or ts > last[node]:
            last[node] = ts

    if not first or t_max is None or t_max <= t_min:
        return None

    span = t_max - t_min
    main = {
        node for node in first
        if (first[node] - t_min) <= start_frac * span
        and (t_max - last[node]) <= end_frac * span
    }

    if not main or len(main) == len(first):
        return set(first.keys())
    return main


def get_main_senders(log_path, send_events=None, start_frac=0.05, end_frac=0.05):
    """
    Best-effort detection of the flow-of-interest sender nodes.

    send_events: optional iterable of (timestamp, node_label) for 's' events,
                 needed for the heuristic path. Pass None to only try metadata
                 (e.g. when tailing a live log before the run has finished).

    Returns (senders_or_None, source) where senders is a set of node labels
    (e.g. {'m3-218', ...}) or None if detection failed entirely, and source
    is a short human-readable string for logging.
    """
    info_path = find_experiment_info(log_path)
    if info_path:
        senders = parse_main_senders_from_info(info_path)
        if senders:
            return senders, f"metadata ({os.path.basename(info_path)})"

    if send_events is not None:
        senders = detect_main_senders_heuristic(send_events, start_frac, end_frac)
        if senders:
            return senders, "heuristic (temporal activity span)"

    return None, "none"
