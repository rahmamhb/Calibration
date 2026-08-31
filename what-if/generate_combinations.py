#!/usr/bin/env python3
# =============================================================================
# generate_combinations.py
# Generates ~100 CSMA MAC-configuration combinations for the what-if study,
# chosen to spread across the full aggressiveness/robustness range of
# CSMA-CA (collision probability vs. latency/energy trade-off) so the
# resulting dataset shows real differences in the measured KPIs.
#
# Algorithm:
#   1. Enumerate the full valid grid (MAX_BE >= MIN_BE).
#   2. Always include a handful of named corner/baseline combos.
#   3. Fill the rest with farthest-point ("MaxiMin") sampling over the
#      normalized parameter space, so the selection spreads across
#      corners/edges/interior rather than clustering near the defaults.
#
# Usage:
#   python3 generate_combinations.py
# =============================================================================

import csv
import random

from wi_common import COMBINATIONS_CSV

MIN_BE_VALUES            = [0, 1, 2, 3, 4]                  # Contiki-NG default = 3
MAX_BE_VALUES             = [3, 4, 5, 6, 7, 8]               # default = 5; constrained MAX_BE >= MIN_BE
MAX_BACKOFF_VALUES        = [1, 2, 3, 4, 5, 6, 8, 10]        # default = 5
MAX_FRAME_RETRIES_VALUES  = [0, 1, 2, 3, 5, 7, 10]           # Makefile default = 7

SEED     = 42
N_TARGET = 100

# Named corner/baseline combos, always included (must be valid: MAX_BE >= MIN_BE
# and every value present in the value sets above).
CORNER_COMBOS = [
    (3, 5, 5, 7),     # Contiki-NG / Makefile defaults (baseline)
    (0, 3, 1, 0),      # most aggressive: short backoff, gives up fast, no retries
    (4, 8, 10, 10),    # most conservative: long backoff, persistent, many retries
    (0, 3, 10, 10),    # frequent collisions, but recovered via heavy retry/backoff persistence
    (4, 8, 1, 0),      # avoids collisions upfront, but drops on any residual failure
    (0, 8, 10, 0),     # max BE spread + max backoff attempts, zero frame-retry tolerance
    (4, 4, 1, 10),     # fixed (non-adaptive) wide backoff window, gives up fast on channel-busy, max retries
    (3, 3, 8, 10),     # fixed backoff window at default MIN_BE, high backoff/retry tolerance
]


def valid_grid():
    grid = []
    for min_be in MIN_BE_VALUES:
        for max_be in MAX_BE_VALUES:
            if max_be < min_be:
                continue
            for max_backoff in MAX_BACKOFF_VALUES:
                for max_frame_retries in MAX_FRAME_RETRIES_VALUES:
                    grid.append((min_be, max_be, max_backoff, max_frame_retries))
    return grid


def normalize(combo):
    min_be, max_be, max_backoff, max_frame_retries = combo
    return (
        (min_be - min(MIN_BE_VALUES)) / (max(MIN_BE_VALUES) - min(MIN_BE_VALUES)),
        (max_be - min(MAX_BE_VALUES)) / (max(MAX_BE_VALUES) - min(MAX_BE_VALUES)),
        (max_backoff - min(MAX_BACKOFF_VALUES)) / (max(MAX_BACKOFF_VALUES) - min(MAX_BACKOFF_VALUES)),
        (max_frame_retries - min(MAX_FRAME_RETRIES_VALUES)) / (max(MAX_FRAME_RETRIES_VALUES) - min(MAX_FRAME_RETRIES_VALUES)),
    )


def sq_dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def maximin_select(candidates, selected, n_target, rng):
    """Greedily grow `selected` by repeatedly adding the candidate that
    maximizes the minimum distance to everything already selected."""
    candidates = [c for c in candidates if c not in selected]
    norm_selected  = [normalize(c) for c in selected]
    norm_candidates = {c: normalize(c) for c in candidates}

    while len(selected) < n_target and norm_candidates:
        best_combo = None
        best_min_dist = -1.0
        # Shuffle traversal order so tie-breaks are seed-controlled, not
        # dependent on dict/grid enumeration order.
        ordered = list(norm_candidates.items())
        rng.shuffle(ordered)
        for combo, norm_combo in ordered:
            min_dist = min(sq_dist(norm_combo, s) for s in norm_selected)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_combo = combo
        selected.append(best_combo)
        norm_selected.append(norm_candidates.pop(best_combo))

    return selected


def main():
    rng = random.Random(SEED)
    grid = valid_grid()
    print(f"  Valid grid size (MAX_BE >= MIN_BE): {len(grid)}")

    missing_corners = [c for c in CORNER_COMBOS if c not in grid]
    if missing_corners:
        raise ValueError(f"Corner combos not in valid grid: {missing_corners}")

    selected = list(CORNER_COMBOS)
    print(f"  Seeded with {len(selected)} named corner/baseline combos")

    selected = maximin_select(grid, selected, N_TARGET, rng)
    print(f"  Total combos selected: {len(selected)}")

    # Stable, readable ordering for the output file.
    selected.sort()

    rows = []
    for i, (min_be, max_be, max_backoff, max_frame_retries) in enumerate(selected, start=1):
        rows.append({
            "id":                     i,
            "CSMA_MIN_BE":            min_be,
            "CSMA_MAX_BE":            max_be,
            "CSMA_MAX_BACKOFF":       max_backoff,
            "CSMA_MAX_FRAME_RETRIES": max_frame_retries,
        })

    with open(COMBINATIONS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "CSMA_MIN_BE", "CSMA_MAX_BE", "CSMA_MAX_BACKOFF", "CSMA_MAX_FRAME_RETRIES",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Wrote {len(rows)} combinations to {COMBINATIONS_CSV}")

    # Sanity-check: per-parameter marginal histogram.
    for label, values, param_key in [
        ("CSMA_MIN_BE",            MIN_BE_VALUES,           "CSMA_MIN_BE"),
        ("CSMA_MAX_BE",            MAX_BE_VALUES,            "CSMA_MAX_BE"),
        ("CSMA_MAX_BACKOFF",       MAX_BACKOFF_VALUES,       "CSMA_MAX_BACKOFF"),
        ("CSMA_MAX_FRAME_RETRIES", MAX_FRAME_RETRIES_VALUES, "CSMA_MAX_FRAME_RETRIES"),
    ]:
        counts = {v: 0 for v in values}
        for row in rows:
            counts[row[param_key]] += 1
        hist = "  ".join(f"{v}:{counts[v]}" for v in values)
        print(f"  {label:<24s} {hist}")


if __name__ == "__main__":
    main()
