#!/usr/bin/env python3
# =============================================================================
# prebuild_firmware.py
# Serially builds (and caches) one Z1 firmware pair (sender.z1/receiver.z1)
# per unique (CSMA_MIN_BE, CSMA_MAX_BE, CSMA_MAX_BACKOFF, CSMA_MAX_FRAME_RETRIES,
# NB_PACKETS) combination required by combinations.csv x ACTIVE_TOPOLOGIES.
#
# MUST run to completion as a single serial process (never parallel/array) —
# every build shares the same host-mounted contiki-ng source tree, and
# concurrent `make clean` + `make` invocations against that tree would race.
#
# Usage:
#   python3 prebuild_firmware.py            # build everything still missing
#   python3 prebuild_firmware.py --limit 2  # smoke-test: build at most 2 keys
# =============================================================================

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from wi_common import (
    COMBINATIONS_CSV, DOCKER_IMAGE, CONTIKI_DIR, FIRMWARE_EXAMPLE_DIR,
    FIRMWARE_CACHE_DIR, MANIFEST_CSV, LOGS_DIR, required_firmware_keys,
)

MANIFEST_FIELDS = [
    "key", "csma_min_be", "csma_max_be", "csma_max_backoff", "csma_max_frame_retries",
    "nb_packets", "build_dir", "sender_path", "receiver_path",
    "build_started_ts", "build_finished_ts", "status", "docker_image",
]


def load_manifest():
    if not Path(MANIFEST_CSV).exists():
        return {}
    with open(MANIFEST_CSV, newline="") as f:
        return {row["key"]: row for row in csv.DictReader(f)}


def append_manifest_row(row):
    write_header = not Path(MANIFEST_CSV).exists()
    with open(MANIFEST_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def docker_pull():
    print(f"[prebuild] Pulling {DOCKER_IMAGE} ...")
    result = subprocess.run(["docker", "pull", DOCKER_IMAGE])
    if result.returncode != 0:
        print(f"[prebuild] ERROR: failed to pull {DOCKER_IMAGE}")
        sys.exit(1)


def build_one(key, min_be, max_be, max_backoff, max_frame_retries, nb_packets):
    log_path = f"{LOGS_DIR}/firmware/{key}.log"
    build_started_ts = time.time()

    make_cmd = (
        f"cd /home/user/contiki-ng/examples/radio-link-quality && "
        f"make TARGET=z1 clean && "
        f"make TARGET=z1 "
        f"CSMA_MIN_BE={min_be} CSMA_MAX_BE={max_be} "
        f"CSMA_MAX_BACKOFF={max_backoff} CSMA_MAX_FRAME_RETRIES={max_frame_retries} "
        f"NB_PACKETS={nb_packets} sender.z1 receiver.z1"
    )
    # contiker/contiki-ng's entrypoint (remap-user.sh) remaps its internal
    # "user" account to LOCAL_UID/LOCAL_GID before running the command — this
    # is required for the container to have write access to the host-mounted
    # contiki-ng tree, which is owned by the host user (not the image's
    # default uid 1000).
    docker_cmd = [
        "docker", "run", "--rm",
        "-e", f"LOCAL_UID={os.getuid()}",
        "-e", f"LOCAL_GID={os.getgid()}",
        "-v", f"{CONTIKI_DIR}:/home/user/contiki-ng",
        DOCKER_IMAGE,
        "bash", "-lc", make_cmd,
    ]

    print(f"[prebuild] Building {key} ...")
    with open(log_path, "w") as log_file:
        log_file.write(f"$ {' '.join(docker_cmd)}\n\n")
        log_file.flush()
        result = subprocess.run(docker_cmd, stdout=log_file, stderr=subprocess.STDOUT)

    build_finished_ts = time.time()

    sender_src   = Path(f"{FIRMWARE_EXAMPLE_DIR}/build/z1/sender.z1")
    receiver_src = Path(f"{FIRMWARE_EXAMPLE_DIR}/build/z1/receiver.z1")

    ok = (
        result.returncode == 0
        and sender_src.exists() and sender_src.stat().st_size > 0
        and receiver_src.exists() and receiver_src.stat().st_size > 0
        and sender_src.stat().st_mtime >= build_started_ts
        and receiver_src.stat().st_mtime >= build_started_ts
    )

    build_dir = f"{FIRMWARE_CACHE_DIR}/{key}"
    row = {
        "key": key,
        "csma_min_be": min_be, "csma_max_be": max_be,
        "csma_max_backoff": max_backoff, "csma_max_frame_retries": max_frame_retries,
        "nb_packets": nb_packets,
        "build_dir": build_dir,
        "sender_path": "", "receiver_path": "",
        "build_started_ts": int(build_started_ts), "build_finished_ts": int(build_finished_ts),
        "status": "failed", "docker_image": DOCKER_IMAGE,
    }

    if not ok:
        print(f"[prebuild]  x  {key} FAILED (exit {result.returncode}) — see {log_path}")
        append_manifest_row(row)
        return False

    dest_dir = Path(f"{build_dir}/build/z1")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sender_src, dest_dir / "sender.z1")
    shutil.copy2(receiver_src, dest_dir / "receiver.z1")
    for map_name in ("sender.map", "receiver.map"):
        map_src = Path(f"{FIRMWARE_EXAMPLE_DIR}/build/z1/{map_name}")
        if map_src.exists():
            shutil.copy2(map_src, dest_dir / map_name)

    row["sender_path"]   = str(dest_dir / "sender.z1")
    row["receiver_path"] = str(dest_dir / "receiver.z1")
    row["status"] = "ok"
    append_manifest_row(row)
    print(f"[prebuild]  ok {key} ({build_finished_ts - build_started_ts:.0f}s)")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Build at most N missing keys (smoke-test)")
    parser.add_argument("--check", action="store_true",
                         help="Only report missing/cached counts and exit "
                              "(0 if nothing missing, 1 otherwise) — no build")
    parser.add_argument("--nb-packets", type=int, default=None,
                         help="Build firmware for this NB_PACKETS value instead of "
                              "the one(s) implied by ACTIVE_TOPOLOGIES in wi_common.py "
                              "— use this to prebuild ahead of activating a topology "
                              "(e.g. Sc3's NB_PACKETS=5) before its other config "
                              "(radio params) is ready.")
    args = parser.parse_args()

    os.makedirs(f"{LOGS_DIR}/firmware", exist_ok=True)
    os.makedirs(FIRMWARE_CACHE_DIR, exist_ok=True)

    with open(COMBINATIONS_CSV, newline="") as f:
        combinations = list(csv.DictReader(f))

    nb_packets_values = [args.nb_packets] if args.nb_packets is not None else None
    if nb_packets_values:
        print(f"[prebuild] --nb-packets {args.nb_packets}: overriding ACTIVE_TOPOLOGIES-derived set")
    needed = required_firmware_keys(combinations, nb_packets_values=nb_packets_values)
    manifest = load_manifest()
    done_ok = {k for k, row in manifest.items() if row.get("status") == "ok"}

    missing = {k: v for k, v in needed.items() if k not in done_ok}
    print(f"[prebuild] {len(needed)} required keys, {len(done_ok)} already cached, "
          f"{len(missing)} to build")

    if args.check:
        if missing:
            print(f"[prebuild] NOT READY — missing keys: {sorted(missing)}")
            sys.exit(1)
        print("[prebuild] READY — all required firmware cached.")
        return

    if args.limit is not None:
        missing = dict(list(missing.items())[: args.limit])
        print(f"[prebuild] --limit {args.limit}: building only {len(missing)} key(s)")

    if not missing:
        print("[prebuild] Nothing to build.")
        return

    docker_pull()

    failures = []
    for i, (key, (min_be, max_be, max_backoff, max_frame_retries, nb_packets)) in enumerate(missing.items(), start=1):
        print(f"[prebuild] ({i}/{len(missing)}) key={key}")
        ok = build_one(key, min_be, max_be, max_backoff, max_frame_retries, nb_packets)
        if not ok:
            failures.append(key)

    print(f"\n[prebuild] Done. Built OK: {len(missing) - len(failures)}  Failed: {len(failures)}")
    if failures:
        print(f"[prebuild] Failed keys: {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
