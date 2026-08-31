#!/usr/bin/env python3
# =============================================================================
# tools/run_analysis.py
# Parses serial.log and computes per-node metrics:
#   delay, loss rate, throughput, mean RSSI
#
# Usage:
#   python3 tools/run_analysis.py --dir ./results/cooja --nodes 3
# =============================================================================

import argparse
import csv
import glob
import os
import re
import sys


# ── Helpers ──────────────────────────────────────────────────────────────────

def time_to_seconds(time_str):
    return float(time_str)


def extract_key(rest):
    """Build a unique packet key from sender IPv6 last 4 chars + packet_id."""
    if len(rest) < 3:
        return None
    ipv6      = rest[1]
    packet_id = rest[2]
    last4     = ipv6[-4:]
    return last4 + packet_id


def sender_node_id(line):
    """
    Extract the sender node id from a receive line.
    Cooja format:  timestamp;ID:X;r fe80::c30c:0:0:Y  packet_id rssi=-XX
    The last non-zero segment of the IPv6 address encodes the mote ID.
    Returns an integer node id, or None if not found.
    """
    sender_match = re.search(r';r\s+([0-9a-f:]+)\s+', line)
    if not sender_match:
        return None
    ip       = sender_match.group(1)
    segments = ip.split(':')
    # Walk segments from the end — first non-zero integer is the node id
    for seg in reversed(segments):
        if seg and seg != '0':
            try:
                return int(seg, 16)
            except ValueError:
                pass
    return None


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_log(serial_path):
    """
    Single-pass parse of serial.log.
    Packets whose receive line appears before their send line in the file
    are correctly counted as lost — the packet was not yet registered when
    the receive arrived, which reflects the true drop behavior in FIT.

    Returns:
        packet_dict   — {key: (send_time, recv_time)}
        rssi_by_node  — {node_id: [rssi_value, ...]}
        duration      — total log duration in seconds
        all_rssi      — flat list of all RSSI values (for std/min)
        delay_list    — list of per-packet delays in seconds (for std)
        sent_by_node  — {node_id: count} packets sent per node
        recv_by_node  — {node_id: count} packets received per node
        total_recv    — raw count of all receive events (used when key matching fails)
    """
    packet_dict  = {}
    rssi_by_node = {}
    all_rssi     = []
    sent_by_node = {}
    recv_by_node = {}
    total_recv   = 0  # independent counter — correct for FitIoT where IP keys differ
    # Map IPv6 last-4 chars → node label (e.g. "1062" → "109") built from send events
    ipv6_suffix_to_node = {}
    starting_time = 0.0
    last_time     = 0.0
    snf_counter   = 0  # unique key counter for synthetic "Service not found" entries

    with open(serial_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or "CSMA" in line:
                continue

            parts = line.split(';')
            if len(parts) < 3:
                continue

            timestamp   = parts[0]
            event_block = parts[2].split()
            if not event_block:
                continue

            event = event_block[0]

            try:
                t = time_to_seconds(timestamp)
            except ValueError:
                continue

            if starting_time == 0.0:
                starting_time = t
            last_time = t

            # ── Send event ────────────────────────────────────────────────
            if event == "s":
                key = extract_key(event_block)
                if key:
                    packet_dict[key] = (timestamp, None)
                    try:
                        src = parts[1].split('-')[1]
                    except (IndexError, ValueError):
                        src = event_block[1] if len(event_block) >= 2 else "unknown"
                    sent_by_node[src] = sent_by_node.get(src, 0) + 1
                    # Record IPv6 suffix → node label mapping for use in receive events
                    if len(event_block) >= 2:
                        suffix = event_block[1][-4:]
                        ipv6_suffix_to_node[suffix] = src
            # ── Receive event ─────────────────────────────────────────────
            elif event == "r":
                total_recv += 1
                key = extract_key(event_block)
                if key and key in packet_dict:
                    packet_dict[key] = (packet_dict[key][0], timestamp)

                rssi_match = re.search(r'rssi=(-?\d+)', line)
                if rssi_match:
                    rssi  = int(rssi_match.group(1))
                    nid   = sender_node_id(line)
                    label = str(nid) if nid is not None else "unknown"
                    rssi_by_node.setdefault(label, []).append(rssi)
                    all_rssi.append(rssi)

                # Use IPv6 suffix mapping so recv_by_node keys match sent_by_node
                if len(event_block) >= 2:
                    suffix = event_block[1][-4:]
                    sender = ipv6_suffix_to_node.get(suffix)
                    if sender:
                        recv_by_node[sender] = recv_by_node.get(sender, 0) + 1

            # ── FitIoT "Service not found" — a send attempt that was rejected ──
            # Only applies to FitIoT logs (m3-X node format); Cooja logs never emit this.
            # Use substring check on parts[2] to handle rare BOM-prefixed lines.
            elif parts[1].startswith("m3-") and "Service" in parts[2] and "not found" in parts[2]:
                try:
                    src = parts[1].split('-')[1]
                except (IndexError, ValueError):
                    src = "unknown"
                sent_by_node[src] = sent_by_node.get(src, 0) + 1
                snf_counter += 1
                packet_dict[f"__snf_{snf_counter}"] = (timestamp, None)

    # ── Per-packet delays (filter r < s timestamp anomalies) ─────────────
    delay_list = []
    for send_time, recv_time in packet_dict.values():
        if send_time is not None and recv_time is not None:
            s = time_to_seconds(send_time)
            r = time_to_seconds(recv_time)
            if r > s:
                delay_list.append(r - s)

    duration = last_time - starting_time
    return packet_dict, rssi_by_node, duration, all_rssi, delay_list, sent_by_node, recv_by_node, total_recv


# ── Metric computations ───────────────────────────────────────────────────────

def compute_delay(packet_dict):
    total = 0.0
    count = 0
    for send_time, recv_time in packet_dict.values():
        if send_time is not None and recv_time is not None:
            s = time_to_seconds(send_time)
            r = time_to_seconds(recv_time)
            if r >= s:
                total += (r - s)
                count += 1
    return total / count if count else 0.0


def compute_delay_std(delay_list):
    """NEW — standard deviation of per-packet delays."""
    if len(delay_list) < 2:
        return 0.0
    mean = sum(delay_list) / len(delay_list)
    variance = sum((d - mean) ** 2 for d in delay_list) / len(delay_list)
    return variance ** 0.5


def compute_per_node_stats(sent_by_node, recv_by_node):
    """
    NEW — compute per-node PRR and derive:
      std_loss_rate    : std of per-node loss rates (%)
      per_node_min_prr : worst node packet reception ratio (0-1)
    """
    per_node_prr = []
    for node, n_sent in sent_by_node.items():
        n_recv = recv_by_node.get(node, 0)
        if n_sent > 0:
            per_node_prr.append(n_recv / n_sent)

    if not per_node_prr:
        return 0.0, 0.0

    per_node_loss = [(1 - prr) * 100 for prr in per_node_prr]
    mean_loss = sum(per_node_loss) / len(per_node_loss)
    std_loss  = (sum((l - mean_loss) ** 2 for l in per_node_loss) / len(per_node_loss)) ** 0.5
    min_prr   = min(per_node_prr)
    return std_loss, min_prr


def compute_lossrate(packet_dict, total_recv=None):
    total = sum(1 for s, _ in packet_dict.values() if s is not None)
    # Sequence numbers wrap (8-bit counter resets every ~39 s), so the same key
    # is reused many times.  packet_dict collapses all reuses into one entry,
    # making key-matched counts useless for overall loss.  total_recv is an
    # independent counter that increments on every 'r' event — always use it.
    if total_recv is not None and total_recv > 0:
        received = min(total_recv, total)
    else:
        matched  = sum(1 for s, r in packet_dict.values() if s is not None and r is not None)
        received = matched
    lost = total - received
    return (lost / total * 100) if total else 0.0


def compute_throughput(packet_dict, duration, nb_nodes, total_recv=None, msg_size=8):
    total_sent = sum(1 for s, _ in packet_dict.values() if s is not None)
    if total_recv is not None and total_recv > 0:
        received = min(total_recv, total_sent)
    else:
        received = sum(1 for s, r in packet_dict.values() if s is not None and r is not None)
    if received and duration:
        return ((received * msg_size) / duration) / nb_nodes
    return 0.0


def mean_rssi(rssi_by_node):
    """Returns {node_id: mean_rssi} for all nodes that have RSSI data."""
    return {
        nid: round(sum(vals) / len(vals), 2)
        for nid, vals in rssi_by_node.items()
        if vals
    }


# ── OML (radio monitoring) ────────────────────────────────────────────────────

def parse_oml(oml_path):
    """
    Parse an OML text file produced by FIT IoT-Lab radio monitoring.
    Returns a list of RSSI floats (dBm) from the radio_sniffer stream.
    OML text row format: exp_time schema_id seq_num col0 col1 ... colN
    """
    rssi_values   = []
    radio_schema  = None  # schema id string for radio_sniffer
    rssi_col      = None  # 0-based index among value columns

    with open(oml_path, 'r') as f:
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
            # Need at least: exp_time schema_id seq_num + rssi_col+1 value columns
            if len(parts) < 4 or parts[1] != radio_schema:
                continue
            idx = 3 + rssi_col
            if idx < len(parts):
                try:
                    rssi_values.append(float(parts[idx]))
                except ValueError:
                    pass

    return rssi_values


def load_oml_rssi(oml_dir):
    """
    Scan oml_dir for m3_N.oml files (one per sender node).
    Returns {str(N): [rssi_values]} for nodes that have non-empty OML data.
    """
    result = {}
    for path in glob.glob(os.path.join(oml_dir, 'm3_*.oml')):
        basename = os.path.basename(path)
        try:
            node_id = basename.split('_')[1].split('.')[0]
        except IndexError:
            continue
        vals = parse_oml(path)
        if vals:
            result[node_id] = vals
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir',     required=True, help='Results directory containing serial.log')
    parser.add_argument('--nodes',   type=int, default=3, help='Number of sender nodes')
    parser.add_argument('--oml-dir', default=None,
                        help='Directory with m3_N.oml files from radio monitoring (FIT IoT-Lab)')
    args = parser.parse_args()

    serial_path = os.path.join(args.dir, 'serial.log')
    csv_path    = os.path.join(args.dir, 'metrics.csv')

    if not os.path.exists(serial_path):
        print(f"✗ serial.log not found in {args.dir}")
        sys.exit(1)

    print(f"→ Parsing: {serial_path}")
    packet_dict, rssi_by_node, duration, all_rssi, delay_list, sent_by_node, recv_by_node, total_recv = parse_log(serial_path)

    delay      = compute_delay(packet_dict)
    delay_std  = compute_delay_std(delay_list)                          # NEW
    lossrate   = compute_lossrate(packet_dict, total_recv=total_recv)
    throughput = compute_throughput(packet_dict, duration, args.nodes, total_recv=total_recv)
    std_loss_rate, per_node_min_prr = compute_per_node_stats(            # NEW
        sent_by_node, recv_by_node
    )

    # OML radio monitoring takes priority over firmware-reported RSSI
    oml_dir = args.oml_dir or args.dir
    oml_rssi = load_oml_rssi(oml_dir)
    if oml_rssi:
        print(f"  RSSI source: OML radio monitoring ({len(oml_rssi)} node(s))")
        rssi_means = mean_rssi(oml_rssi)
        flat_rssi  = [v for vals in oml_rssi.values() for v in vals]
    else:
        rssi_means = mean_rssi(rssi_by_node)
        flat_rssi  = all_rssi   # NEW — use flat list from parse_log

    # NEW — RSSI std and min
    if flat_rssi:
        rssi_mean_val = sum(flat_rssi) / len(flat_rssi)
        rssi_std_val  = (sum((r - rssi_mean_val) ** 2 for r in flat_rssi) / len(flat_rssi)) ** 0.5
        rssi_min_val  = min(flat_rssi)
    else:
        rssi_mean_val = None
        rssi_std_val  = None
        rssi_min_val  = None

    print(f"  Delay      : {delay:.4f} s")
    print(f"  Delay std  : {delay_std:.4f} s")                          # NEW
    print(f"  Loss rate  : {lossrate:.2f} %")
    print(f"  Std loss   : {std_loss_rate:.2f} %")                      # NEW
    print(f"  Min PRR    : {per_node_min_prr:.4f}")                     # NEW
    print(f"  Throughput : {throughput:.2f} bytes/s/node")
    if rssi_means:
        global_rssi = round(sum(rssi_means.values()) / len(rssi_means), 2)
        print(f"  Mean RSSI  : {global_rssi} dBm")
        print(f"  Std  RSSI  : {round(rssi_std_val, 4) if rssi_std_val is not None else 'N/A'} dBm")   # NEW
        print(f"  Min  RSSI  : {rssi_min_val} dBm")                    # NEW
    else:
        global_rssi = None
        print("  RSSI       : no data found in log")

    # ── Write metrics.csv ────────────────────────────────────────────────────
    fieldnames = [
        'mean_rssi_dbm', 'std_rssi_dbm', 'min_rssi_dbm',   # NEW fields
        'loss_rate_pct', 'throughput_pkt_s',
        'mean_delay_s',  'std_delay_s',                      # NEW field
        'std_loss_rate', 'per_node_min_prr',                 # NEW fields
    ]
    rows = [{
        'mean_rssi_dbm':    round(global_rssi,     2) if global_rssi    is not None else None,
        'std_rssi_dbm':     round(rssi_std_val,    4) if rssi_std_val   is not None else None,  # NEW
        'min_rssi_dbm':     round(rssi_min_val,    2) if rssi_min_val   is not None else None,  # NEW
        'loss_rate_pct':    round(lossrate,         2),
        'throughput_pkt_s': round(throughput,       2),
        'mean_delay_s':     round(delay,            6),
        'std_delay_s':      round(delay_std,        6),   # NEW
        'std_loss_rate':    round(std_loss_rate,    4),   # NEW
        'per_node_min_prr': round(per_node_min_prr, 4),  # NEW
    }]

    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  ✓ Saved to: {csv_path}")
