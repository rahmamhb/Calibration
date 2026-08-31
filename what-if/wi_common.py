#!/usr/bin/env python3
# =============================================================================
# wi_common.py
# Shared constants/helpers for the MAC (CSMA) what-if pipeline:
#   generate_combinations.py -> combinations.csv
#   prebuild_firmware.py     -> firmware/cache/<key>/build/z1/{sender,receiver}.z1
#   run_one_whatif_sim.py    -> dataset.csv
#   submit_whatif.sh         -> sbatch jobs
# =============================================================================

import os

WHATIF_DIR       = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR      = os.path.dirname(WHATIF_DIR)                      # .../cooja-sim
CONTIKI_DIR      = "/home/mihoubrahma/contiki-ng"
FIRMWARE_EXAMPLE_DIR = f"{CONTIKI_DIR}/examples/radio-link-quality"
COOJA_PATH       = f"{CONTIKI_DIR}/tools/cooja"
DOCKER_IMAGE     = "contiker/contiki-ng"

COMBINATIONS_CSV = f"{WHATIF_DIR}/combinations.csv"
FIRMWARE_DIR     = f"{WHATIF_DIR}/firmware"
FIRMWARE_CACHE_DIR = f"{FIRMWARE_DIR}/cache"
MANIFEST_CSV     = f"{FIRMWARE_DIR}/manifest.csv"
TEMPLATE_CSC     = f"{PROJECT_DIR}/templates/radio-link-quality.csc"
DATASET_RUNS_DIR = f"{WHATIF_DIR}/dataset_runs"
LOGS_DIR         = f"{WHATIF_DIR}/logs"

# ── Topologies ────────────────────────────────────────────────────────────────
# Each topology carries its own NB_PACKETS (baked into firmware) and its own
# calibrated LogisticLoss radio params (injected into the .csc at run time).
# RX_SENSITIVITY_DBM is fixed at -100.0 for all topologies, matching the
# existing convention elsewhere in this repo (predict_params.py).
TOPOLOGIES = {
    "Sc4": {
        "positions":            f'{PROJECT_DIR}/Scenarios Setup/node_positions_Sc4.json',
        "nb_senders":           20,
        "nb_packets":           15,
        "rx_sensitivity":       -100.0,
        "rssi_inflection_point": -51.621,
        "path_loss_exponent":   2.0707,
        "awgn_sigma":           15.471,
    },
    "Sc9": {
        "positions":            f'{PROJECT_DIR}/Scenarios Setup/node_positions_Sc9.json',
        "nb_senders":           5,
        "nb_packets":           15,
        "rx_sensitivity":       -100.0,
        "rssi_inflection_point": -96.6882,
        "path_loss_exponent":   1.7063,
        "awgn_sigma":           25.5253,
    },
    "Sc3": {
        "positions":            f'{PROJECT_DIR}/Scenarios Setup/node_positions_Sc3.json', "nb_senders": 10,
        "nb_packets":           5,
        "rx_sensitivity":       -100.0,
        "rssi_inflection_point": -77.7012,
        "path_loss_exponent":   2.9310,
        "awgn_sigma":           7.5984,
    },
    # Sc3's NB_PACKETS=5 firmware set (100 images) was prebuilt via
    # `python3 prebuild_firmware.py --nb-packets 5` (0 failures). Transmitting
    # range is left at the template default (40.0), matching the value
    # supplied for Sc3.
}

ACTIVE_TOPOLOGIES = ["Sc4", "Sc9", "Sc3"]

SIM_DURATION_MIN = 10   # bumped from the RF pipeline's 5 — conservative CSMA
WALL_TIMEOUT_MIN = 90   # combos + the 21-mote Sc4 topology need more time


def firmware_key(min_be, max_be, max_backoff, max_frame_retries, nb_packets):
    """Deterministic cache key for one (CSMA config, NB_PACKETS) firmware build.
    Defined once here and imported everywhere else to avoid key-format drift."""
    return f"mb{min_be}_MB{max_be}_bo{max_backoff}_fr{max_frame_retries}_np{nb_packets}"


def firmware_cache_dir(key):
    return f"{FIRMWARE_CACHE_DIR}/{key}"


def dataset_csv_path(topology):
    """One dataset file per scenario (what-if/dataset_<topology>.csv), matching
    this repo's existing results/Scenario0N per-scenario convention."""
    return f"{WHATIF_DIR}/dataset_{topology}.csv"


def required_firmware_keys(combinations, nb_packets_values=None):
    """
    combinations: list of dicts with CSMA_MIN_BE/CSMA_MAX_BE/CSMA_MAX_BACKOFF/
    CSMA_MAX_FRAME_RETRIES (as in combinations.csv rows).
    nb_packets_values: which NB_PACKETS values to build for. Defaults to the
    distinct NB_PACKETS values across ACTIVE_TOPOLOGIES — pass an explicit list
    to prebuild firmware for a NB_PACKETS value ahead of activating the
    topology that needs it (e.g. Sc3's NB_PACKETS=5, before its radio params
    are available).
    Returns a dict {key: (min_be, max_be, max_backoff, max_frame_retries, nb_packets)}
    for every (combo, nb_packets) pair, deduplicated.
    """
    if nb_packets_values is None:
        nb_packets_values = sorted({TOPOLOGIES[t]["nb_packets"] for t in ACTIVE_TOPOLOGIES})
    keys = {}
    for row in combinations:
        min_be            = int(row["CSMA_MIN_BE"])
        max_be            = int(row["CSMA_MAX_BE"])
        max_backoff       = int(row["CSMA_MAX_BACKOFF"])
        max_frame_retries = int(row["CSMA_MAX_FRAME_RETRIES"])
        for nb_packets in nb_packets_values:
            key = firmware_key(min_be, max_be, max_backoff, max_frame_retries, nb_packets)
            keys[key] = (min_be, max_be, max_backoff, max_frame_retries, nb_packets)
    return keys
