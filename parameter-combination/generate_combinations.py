#!/usr/bin/env python3
# =============================================================================
# generate_combinations.py
# Generates the LogisticLoss parameter grid for the main calibration dataset
# (consumed by scripts/submit_dataset.sh -> tools/run_one_sim.py -> dataset.csv)
# and writes both combinations.csv and a summary.txt into this directory.
#
# The value lists below are the ones actually explored so far (extracted from
# the committed combinations.csv): RSSI_INFLECTION_POINT and AWGN_SIGMA carry
# extra points in some sub-ranges from later rounds that refined/extended the
# original sweep, so their steps aren't perfectly uniform. Running this script
# regenerates the FULL cartesian product of the lists below, which is a
# superset of what's currently in combinations.csv (some combinations haven't
# been run yet) - it does not try to reproduce that file byte-for-byte.
# scripts/submit_dataset.sh already skips ids present in dataset.csv, so
# re-running against the full grid resumes rather than repeats work.
#
# To extend the study, edit the value lists below and re-run.
#
# Usage:
#   python3 generate_combinations.py
# =============================================================================

import csv
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

RX_SENSITIVITY_DBM = [-100.0]

RSSI_INFLECTION_POINT = [
    -120.0, -115.0, -110.0, -105.0, -100.0, -95.0, -90.0,
    -85.0, -83.0, -80.0, -78.0, -75.0, -73.0, -70.0, -68.0, -65.0,
    -60.0, -55.0, -50.0, -45.0, -40.0, -35.0, -30.0,
]

TRANSMITTING_RANGE = [40.0]

PATH_LOSS_EXPONENT = [round(1.0 + 0.25 * i, 2) for i in range(17)]  # 1.0 .. 5.0 step 0.25

AWGN_SIGMA = [round(1.0 + 0.5 * i, 2) for i in range(27)] + [15.0, 17.0, 20.0, 22.0, 23.0]  # 1.0..14.0 step 0.5, plus extended range

COLUMNS = [
    "id", "RX_SENSITIVITY_DBM", "RSSI_INFLECTION_POINT",
    "TRANSMITTING_RANGE", "PATH_LOSS_EXPONENT", "AWGN_SIGMA",
]


def generate_rows():
    rows = []
    i = 1
    for rx in RX_SENSITIVITY_DBM:
        for rip in RSSI_INFLECTION_POINT:
            for tr in TRANSMITTING_RANGE:
                for ple in PATH_LOSS_EXPONENT:
                    for awgn in AWGN_SIGMA:
                        rows.append({
                            "id": i,
                            "RX_SENSITIVITY_DBM": rx,
                            "RSSI_INFLECTION_POINT": rip,
                            "TRANSMITTING_RANGE": tr,
                            "PATH_LOSS_EXPONENT": ple,
                            "AWGN_SIGMA": awgn,
                        })
                        i += 1
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows, path):
    def block(name, values):
        values = sorted(set(values))
        lines = [f"  {name}"]
        if len(values) == 1:
            lines.append(f"    fixed = {values[0]:g}")
            lines.append(f"    count = 1")
        else:
            lines.append(f"    min    = {values[0]:g}")
            lines.append(f"    max    = {values[-1]:g}")
            lines.append(f"    values = {[round(v, 4) for v in values]}")
            lines.append(f"    count  = {len(values)}")
        return "\n".join(lines)

    lines = [
        "=" * 60,
        "COOJA LOGISTICLOSS -- PARAMETER COMBINATION SUMMARY",
        "=" * 60,
        "",
        block("RX_SENSITIVITY_DBM", RX_SENSITIVITY_DBM),
        "",
        block("RSSI_INFLECTION_POINT", RSSI_INFLECTION_POINT),
        "",
        block("TRANSMITTING_RANGE", TRANSMITTING_RANGE),
        "",
        block("PATH_LOSS_EXPONENT", PATH_LOSS_EXPONENT),
        "",
        block("AWGN_SIGMA", AWGN_SIGMA),
        "",
        "-" * 60,
        f"  Total combinations : {len(rows):,}",
        "-" * 60,
        "",
        "Note: RSSI_INFLECTION_POINT and AWGN_SIGMA carry extra points from",
        "later rounds that refined/extended the original sweep, so their",
        "steps are not perfectly uniform (see the value lists above).",
        "=" * 60,
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    rows = generate_rows()
    csv_path = os.path.join(SCRIPT_DIR, "combinations.csv")
    summary_path = os.path.join(SCRIPT_DIR, "summary.txt")
    write_csv(rows, csv_path)
    write_summary(rows, summary_path)
    print(f"Wrote {len(rows):,} combinations to {csv_path}")
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
