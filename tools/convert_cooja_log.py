#!/usr/bin/env python3
# =============================================================================
# convert_cooja_log.py
# Converts Cooja LogListener output → FIT IoT-LAB serial.log format
#
# Cooja format:
#   <ms_since_start>\tID:N\ts fe80::c30c:0:0:2 00000001
#   <ms_since_start>\tID:1\tr fe80::c30c:0:0:2 00000001 rssi=-85 lqi=37 count=1
#
#   where <ms_since_start> is a plain float representing milliseconds
#   elapsed since the simulation started (e.g. 6486.061, 1317.349)
#
# FIT IoT-LAB format:
#   1735900922.447000;m3-2;s fe80::c30c:0:0:2 00000001
#   1735900923.992000;m3-1;r fe80::c30c:0:0:2 00000001 rssi=-85 lqi=37 count=1
#
#   where the timestamp is in seconds (ms / 1000)
#
# Usage:
#   python3 convert_cooja_log.py --input loglistener.txt --output serial.log
# =============================================================================

import argparse
import re
import sys


def cooja_time_to_seconds(time_str):

    try:
        return float(time_str) / 1000.0
    except ValueError:
        return None

def convert(input_path, output_path):
    """
    Read Cooja log and write FIT-compatible serial.log
    """

    line_re = re.compile(
    r"^([\d.]+)\s+ID:(\d+)\s+(.+)$"
    )
    converted = 0
    skipped   = 0

    with open(input_path, "r") as fin, open(output_path, "w") as fout:
        for raw_line in fin:
            line = raw_line.strip()
            m = line_re.match(line)
            if not m:
                skipped += 1
                continue

            time_str  = m.group(1)
            mote_id   = m.group(2)
            event_str = m.group(3)

            # Only keep lines that are actual s/r events
            first_word = event_str.split()[0] if event_str else ""
            if first_word not in ("s", "r"):
                skipped += 1
                continue

            ts = cooja_time_to_seconds(time_str)
            if ts is None:
                skipped += 1
                continue

            # Write in FIT IoT-LAB format:
            # timestamp;m3-N;event_string
            fout.write(f"{ts:.6f};m3-{mote_id};{event_str}\n")
            converted += 1

    print(f"  ✓ Converted {converted} lines ({skipped} skipped)")
    return converted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True, help="Cooja loglistener.txt")
    parser.add_argument("--output", required=True, help="Output serial.log")
    args = parser.parse_args()

    count = convert(args.input, args.output)
    if count == 0:
        print("  ⚠ No lines converted — check input file format")
        sys.exit(1)


if __name__ == "__main__":
    main()
