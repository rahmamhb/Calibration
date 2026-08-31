#!/usr/bin/env python3
# =============================================================================
# get_fitiot_positions.py
# Fetches ALL m3 node positions from a FIT IoT-LAB site once and caches them.
# Subsequent runs just read the cache — no SSH needed.
#
# Usage:
#   # First time (or force refresh):
#   python3 get_fitiot_positions.py --host mihoub@grenoble.iot-lab.info --refresh
#
#   # Normal use (reads cache, extracts nodes you need):
#   python3 get_fitiot_positions.py \
#       --nodes "2+3+4+5" --receiver 2 --output node_positions.json
#
#   # Just print all cached nodes:
#   python3 get_fitiot_positions.py --list
# =============================================================================

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

# Cache file lives next to this script — shared across all experiments
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE  = os.path.join(SCRIPT_DIR, ".fitiot_nodes_cache.json")


# =============================================================================
# Cache management
# =============================================================================

def fetch_all_nodes(ssh_host):
    """
    SSH into IoT-LAB frontend, fetch info for ALL m3 nodes on the site.
    """
    print(f"  → Connecting to {ssh_host}...")
    site = ssh_host.split("@")[1].split(".")[0]
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "LogLevel=QUIET",
        ssh_host,
        f"iotlab-experiment info -l --site {site}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("  ✗ SSH timed out — is IoT-LAB reachable?")
        sys.exit(1)

    if result.returncode != 0:
        print(f"  ✗ SSH command failed:\n{result.stderr.strip()}")
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  ✗ Could not parse JSON:\n{result.stdout[:300]}")
        sys.exit(1)

    m3_nodes = [
        n for n in data.get("items", [])
        if "m3" in n.get("archi", "") and "m3" in n.get("network_address", "")
    ]

    print(f"  ✓ Retrieved {len(m3_nodes)} m3 nodes from IoT-LAB")
    return m3_nodes


def build_cache(m3_nodes, ssh_host):
    """Build and save cache file from raw node list."""
    site = ssh_host.split("@")[1].split(".")[0]
    cache = {
        "_meta": {
            "site":        site,
            "ssh_host":    ssh_host,
            "fetched_at":  datetime.now().isoformat(),
            "total_nodes": len(m3_nodes)
        }
    }

    skipped = 0
    for node in m3_nodes:
        addr = node.get("network_address", "")
        try:
            node_id = str(int(addr.split("-")[1].split(".")[0]))
        except (IndexError, ValueError):
            continue

        # Skip nodes with unknown coordinates (IoT-LAB returns '--' for these)
        try:
            x = float(node.get("x", 0))
            y = float(node.get("y", 0))
            z = float(node.get("z", 0))
        except (ValueError, TypeError):
            skipped += 1
            continue

        cache[node_id] = {
            "x":               x,
            "y":               y,
            "z":               z,
            "state":           node.get("state", "Unknown"),
            "uid":             node.get("uid", ""),
            "archi":           node.get("archi", ""),
            "network_address": addr
        }

    if skipped:
        print(f"  ⚠ Skipped {skipped} nodes with unknown coordinates ('--')")

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"  ✓ Cache saved: {CACHE_FILE}  ({len(cache)-1} nodes)")
    return cache


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE) as f:
        return json.load(f)


def ensure_cache(ssh_host=None, force_refresh=False):
    cache = load_cache()

    if cache and not force_refresh:
        meta = cache.get("_meta", {})
        print(f"  → Using cached node data ({meta.get('total_nodes','?')} nodes, "
              f"fetched {meta.get('fetched_at','unknown')[:10]})")
        return cache

    if not ssh_host:
        print("  ✗ No cache found. Populate it first:")
        print("      python3 get_fitiot_positions.py --host mihoub@grenoble.iot-lab.info --refresh")
        sys.exit(1)

    print(f"  → {'Refreshing' if force_refresh else 'Building'} node cache from IoT-LAB...")
    nodes = fetch_all_nodes(ssh_host)
    return build_cache(nodes, ssh_host)


# =============================================================================
# Position extraction
# =============================================================================

def extract_positions(cache, node_ids, receiver_id):
    positions = {}

    for nid in node_ids:
        if nid not in cache:
            print(f"  ⚠ m3-{nid} not in cache")
            continue

        node = cache[nid]
        positions[nid] = {
            "x":               node["x"],
            "y":               node["y"],
            "z":               node["z"],
            "state":           node["state"],
            "uid":             node["uid"],
            "network_address": node["network_address"],
            "role":            "receiver" if nid == receiver_id else "sender",
            "cooja_id":        None
        }
        print(f"  ✓ m3-{nid} [{node['state']:8s}]  x={node['x']:7.2f}  "
              f"y={node['y']:7.2f}  z={node['z']:6.3f}  → {positions[nid]['role']}")

    # Assign Cooja IDs: receiver = 1, senders in sorted order
    cooja_id = 1
    if receiver_id in positions:
        positions[receiver_id]["cooja_id"] = cooja_id
        cooja_id += 1
    for nid in sorted(positions.keys()):
        if nid != receiver_id:
            positions[nid]["cooja_id"] = cooja_id
            cooja_id += 1

    return positions


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fetch/cache FIT IoT-LAB node positions"
    )
    parser.add_argument("--host",     help="SSH host e.g. mihoub@grenoble.iot-lab.info")
    parser.add_argument("--refresh",  action="store_true",
                        help="Force re-fetch from IoT-LAB (ignores cache)")
    parser.add_argument("--list",     action="store_true",
                        help="Print all cached nodes and exit")
    parser.add_argument("--nodes",    help="Node IDs to extract e.g. '2+3+4+5'")
    parser.add_argument("--receiver", help="Receiver node ID e.g. '2'")
    parser.add_argument("--output",   help="Output JSON file for selected nodes")
    args = parser.parse_args()

    cache = ensure_cache(ssh_host=args.host, force_refresh=args.refresh)

    # ── List mode ─────────────────────────────────────────────────────────
    if args.list:
        meta = cache.get("_meta", {})
        print(f"\nCached nodes — site: {meta.get('site')}  "
              f"fetched: {meta.get('fetched_at','')[:19]}\n")
        print(f"{'ID':>5}  {'x':>8}  {'y':>8}  {'z':>7}  {'State':<12}  {'UID'}")
        print("-" * 60)
        for nid, info in sorted(
            ((k, v) for k, v in cache.items() if k != "_meta"),
            key=lambda x: int(x[0]) if x[0].isdigit() else -1
        ):
            print(f"m3-{nid:>3}  {info['x']:>8.2f}  {info['y']:>8.2f}  "
                  f"{info['z']:>7.3f}  {info['state']:<12}  {info['uid']}")
        return

    # ── Extract specific nodes ────────────────────────────────────────────
    if not args.nodes or not args.receiver or not args.output:
        parser.print_help()
        sys.exit(1)

    node_ids    = args.nodes.split("+")
    receiver_id = str(args.receiver)

    positions = extract_positions(cache, node_ids, receiver_id)

    if not positions:
        print("  ✗ No positions found for the requested nodes")
        sys.exit(1)

    output = {
        "site":        cache.get("_meta", {}).get("site", "grenoble"),
        "receiver_id": receiver_id,
        "fetched_at":  cache.get("_meta", {}).get("fetched_at", ""),
        "nodes":       positions
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  ✓ Node positions saved: {args.output}")


if __name__ == "__main__":
    main()
