#!/usr/bin/env python3
"""
Synthetic 60-minute FIT IoT-LAB log generator — v2
Corrected version: ground truth removed, KPI statistics aligned with
the LogisticLoss training dataset ranges.

Scenario: Site=Grenoble, Receiver=m3-207, Senders=m3-208..227 (20 nodes)
          15 pkt/s per sender, 60 minutes total, channel=11

4 phases with 3 condition changes:
  Phase 0:  0–15 min  STABLE    — matches baseline 10-min real experiment
  Phase 1: 15–30 min  DEGRADED  — path_loss_exponent ↑, awgn_sigma ↑
  Phase 2: 30–45 min  RECOVERY  — partial improvement
  Phase 3: 45–60 min  CRITICAL  — severe degradation on half the nodes

Per-phase LogisticLoss parameter sets (the "true" parameters your NN will recover):
  STABLE   : path_loss=2.7, awgn=3.0, rssi_inflection=-70, rx_sensitivity=-100
  DEGRADED : path_loss=3.5, awgn=6.0, rssi_inflection=-55, rx_sensitivity=-100
  RECOVERY : path_loss=3.1, awgn=4.5, rssi_inflection=-62, rx_sensitivity=-100
  CRITICAL : path_loss=4.2, awgn=8.0, rssi_inflection=-45, rx_sensitivity=-100

All values are within the training dataset ranges so the NN can predict them.

Outputs (same exact format as real FIT IoT-LAB logs):
  synthetic_serial.log   — serial aggregator log (sends + receives at m3-207)
  synthetic_m3_208.oml   — OML RSSI trace for m3_208
  synthetic_m3_222.oml   — OML RSSI trace for m3_222
"""

import random
import math
import os
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
RANDOM_SEED    = 42
random.seed(RANDOM_SEED)

EXP_DURATION_S = 3600
PKTS_PER_SEC   = 15
CHANNEL        = 11
OML_RATE_HZ    = 922

AGG_START_TS   = 1779500000.0
OML_START_TIME = int(AGG_START_TS) - 14
DOMAIN         = 999999

RECEIVER       = "m3-207"
SENDERS        = [f"m3-{i}" for i in range(208, 228)]

NODE_FE80 = {
    "m3-208": "fe80::9076", "m3-209": "fe80::b379", "m3-210": "fe80::c081",
    "m3-211": "fe80::8875", "m3-212": "fe80::b280", "m3-213": "fe80::8472",
    "m3-214": "fe80::9567", "m3-215": "fe80::9175", "m3-216": "fe80::b369",
    "m3-217": "fe80::9871", "m3-218": "fe80::b582", "m3-219": "fe80::b481",
    "m3-220": "fe80::2160", "m3-221": "fe80::9981", "m3-222": "fe80::3860",
    "m3-223": "fe80::b768", "m3-224": "fe80::b180", "m3-225": "fe80::c068",
    "m3-226": "fe80::b268", "m3-227": "fe80::9377",
}
NODE_FD00 = {k: v.replace("fe80", "fd00") for k, v in NODE_FE80.items()}

# ─────────────────────────────────────────────────────────────
# LOGISTICLOSS PHYSICS
# Implements the exact same formulas as LogisticLoss.java:
#   RSSI(d) = rx_sensitivity + 10*alpha*log10(tx_range/d)
#   PRR(RSSI) = sigmoid(RSSI - rssi_inflection) / (1 + exp(-(RSSI - inflection)))
# ─────────────────────────────────────────────────────────────
TX_RANGE = 100.0  # fixed (not predicted), same as training setup

# Real distances from Grenoble testbed (approximate, based on node grid layout)
# m3-207 is the receiver; distances to each sender in meters
NODE_DIST_TO_207 = {
    "m3-208": 8,  "m3-209": 5,  "m3-210": 22, "m3-211": 12,
    "m3-212": 18, "m3-213": 15, "m3-214": 16, "m3-215": 20,
    "m3-216": 25, "m3-217": 19, "m3-218": 28, "m3-219": 26,
    "m3-220": 35, "m3-221": 30, "m3-222": 32, "m3-223": 27,
    "m3-224": 34, "m3-225": 29, "m3-226": 31, "m3-227": 33,
}

def logistic_rssi(node, alpha, rx_sensitivity, awgn_sigma):
    """Compute instantaneous RSSI for a node using LogisticLoss formula."""
    d = NODE_DIST_TO_207[node]
    d = max(d, 0.01)
    mean_rssi = rx_sensitivity + 10 * alpha * math.log10(TX_RANGE / d)
    # Add AWGN noise (Gaussian)
    noisy = mean_rssi + random.gauss(0, awgn_sigma)
    return max(-91, min(-7, int(round(noisy))))

def logistic_prr(rssi_dbm, rssi_inflection):
    """PRR = sigmoid(RSSI - inflection) as in LogisticLoss.java."""
    x = rssi_dbm - rssi_inflection
    return 1.0 / (1.0 + math.exp(-x))

# ─────────────────────────────────────────────────────────────
# PHASE DEFINITIONS
# Each entry: (start_s, end_s, label, alpha, awgn_sigma, rssi_inflection, rx_sens)
# All parameters are within training dataset ranges.
# ─────────────────────────────────────────────────────────────
PHASES = [
    (0,    900,  "STABLE",    2.7, 3.0, -70.0, -100.0),
    (900,  1800, "DEGRADED",  3.5, 6.0, -55.0, -100.0),
    (1800, 2700, "RECOVERY",  3.1, 4.5, -62.0, -100.0),
    (2700, 3600, "CRITICAL",  4.2, 8.0, -45.0, -100.0),
]
CHANGE_POINTS = [900, 1800, 2700]

# In CRITICAL phase, half the nodes are hit harder
CRITICAL_EXTRA_NODES = set(SENDERS[10:])  # m3-218..m3-227

def get_phase(t_s):
    for ph in PHASES:
        if ph[0] <= t_s < ph[1]:
            return ph
    return PHASES[-1]

def get_params(node, t_s):
    """Return (alpha, awgn_sigma, rssi_inflection, rx_sensitivity) for node at time t."""
    ph = get_phase(t_s)
    _, _, _, alpha, awgn, inflection, rx_sens = ph

    # Critical nodes in CRITICAL phase: push params harder
    if ph[2] == "CRITICAL" and node in CRITICAL_EXTRA_NODES:
        alpha     = min(4.5, alpha + 0.3)
        awgn      = min(10.0, awgn + 1.5)
        inflection = min(-35.0, inflection + 8.0)

    # Smooth 60s blend at phase boundaries
    for cp in CHANGE_POINTS:
        dist = abs(t_s - cp)
        if dist < 60:
            prev_ph = get_phase(cp - 1)
            frac = dist / 60.0
            p_alpha     = prev_ph[3]
            p_awgn      = prev_ph[4]
            p_inflection= prev_ph[5]
            alpha      = frac * alpha      + (1 - frac) * p_alpha
            awgn       = frac * awgn       + (1 - frac) * p_awgn
            inflection = frac * inflection + (1 - frac) * p_inflection

    return alpha, awgn, inflection, rx_sens

# ─────────────────────────────────────────────────────────────
# SERIAL LOG GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_serial_log(out_path):
    print("Generating synthetic_serial.log ...")
    events = []

    events.append((AGG_START_TS, None, "Aggregator started"))

    # Init "Service 190 not found" messages
    INIT_COUNTS = {n: 6 for n in SENDERS}
    for n in ["m3-216", "m3-220", "m3-225"]: INIT_COUNTS[n] = 29
    for n in ["m3-218","m3-219","m3-221","m3-222","m3-223","m3-224","m3-226"]: INIT_COUNTS[n] = 23
    INIT_COUNTS["m3-227"] = 39
    for node, count in INIT_COUNTS.items():
        for _ in range(count):
            events.append((AGG_START_TS + 0.1 + random.uniform(0, 38), node, "Service 190 not found"))

    # Packet events
    STARTUP = 6.2
    for node in SENDERS:
        ip_fe = NODE_FE80[node]
        ip_fd = NODE_FD00[node]
        t = AGG_START_TS + STARTUP + random.uniform(0, 0.15)
        seq = 0
        while True:
            t_offset = t - AGG_START_TS
            if t_offset >= EXP_DURATION_S:
                break
            seq += 1
            seq_hex = f"{seq:08x}"
            events.append((t, node, f"s {ip_fe} {seq_hex}"))

            # Reception decision via LogisticLoss physics
            alpha, awgn, inflection, rx_sens = get_params(node, t_offset)
            rssi = logistic_rssi(node, alpha, rx_sens, awgn)
            prr  = logistic_prr(rssi, inflection)
            if random.random() < prr:
                t_recv = t + random.uniform(0.001, 0.005)
                events.append((t_recv, RECEIVER, f"r {ip_fd} {seq_hex}"))

            t += random.expovariate(PKTS_PER_SEC)

    print(f"  Sorting {len(events)} events ...")
    events.sort(key=lambda x: x[0])

    with open(out_path, "w") as f:
        for ts, node, msg in events:
            if node is None:
                f.write(f"{ts:.6f};{msg}\n")
            else:
                f.write(f"{ts:.6f};{node};{msg}\n")

    print(f"  Done — {len(events)} lines.")

# ─────────────────────────────────────────────────────────────
# OML FILE GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_oml(sender_node, out_path):
    print(f"Generating OML for {sender_node} ...")
    header = (
        f"protocol: 5\n"
        f"domain: {DOMAIN}\n"
        f"start-time: {OML_START_TIME}\n"
        f"sender-id: {sender_node.replace('-','_')}\n"
        f"app-name: control_node_measures\n"
        f"schema: 0 _experiment_metadata subject:string key:string value:string \n"
        f"schema: 2 control_node_measures_radio timestamp_s:uint32 timestamp_us:uint32 channel:uint32 rssi:int32 \n"
        f"content: text\n\n"
    )

    total = int(OML_RATE_HZ * EXP_DURATION_S)
    OML_OFFSET = 10.39

    with open(out_path, "w") as f:
        f.write(header)
        oml_ts = OML_OFFSET
        abs_ts = OML_START_TIME + OML_OFFSET

        for seq in range(1, total + 1):
            t_offset = oml_ts - OML_OFFSET

            # Pick a sender weighted by current PRR (more traffic = more likely to be observed)
            weights = []
            for n in SENDERS:
                alpha, awgn, inflection, rx_sens = get_params(n, t_offset)
                r = logistic_rssi(n, alpha, rx_sens, awgn)
                weights.append(max(0.01, logistic_prr(r, inflection)))

            total_w = sum(weights)
            rnd = random.random() * total_w
            obs_node = SENDERS[-1]
            cumul = 0
            for n, w in zip(SENDERS, weights):
                cumul += w
                if rnd < cumul:
                    obs_node = n
                    break

            alpha, awgn, inflection, rx_sens = get_params(obs_node, t_offset)
            rssi = logistic_rssi(obs_node, alpha, rx_sens, awgn)

            ts_s  = int(abs_ts)
            ts_us = int((abs_ts - ts_s) * 1e6)
            f.write(f"{oml_ts:.6f}\t2\t{seq}\t{ts_s}\t{ts_us}\t{CHANNEL}\t{rssi}\n")

            dt = (1.0 / OML_RATE_HZ) + random.gauss(0, 0.000002)
            oml_ts += dt
            abs_ts += dt

            if seq % 500000 == 0:
                print(f"  ... {seq}/{total} ({100*seq/total:.0f}%)")

    print(f"  Done — {total} records.")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    OUT = "/home/rahma/Desktop/unified_workflow/results/Scenario04/synthetic_logs_v2"
    os.makedirs(OUT, exist_ok=True)

    print("=" * 60)
    print("Synthetic 60-min FIT IoT-LAB log generator  v2")
    print("Parameters aligned with LogisticLoss training dataset")
    print()
    for ph in PHASES:
        print(f"  {ph[2]:10s}  {ph[0]//60}-{ph[1]//60}min  "
              f"alpha={ph[3]}  awgn={ph[4]}  inflection={ph[5]}")
    print("=" * 60)

    generate_serial_log(os.path.join(OUT, "synthetic_serial.log"))
    generate_oml("m3_224", os.path.join(OUT, "synthetic_m3_224.oml"))
    generate_oml("m3_225", os.path.join(OUT, "synthetic_m3_225.oml"))
    generate_oml("m3_226", os.path.join(OUT, "synthetic_m3_226.oml"))
    generate_oml("m3_227", os.path.join(OUT, "synthetic_m3_227.oml"))
    print("\nFiles:")
    for f in os.listdir(OUT):
        size = os.path.getsize(os.path.join(OUT, f))
        print(f"  {f}: {size/1e6:.1f} MB")
