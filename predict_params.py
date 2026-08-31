#!/usr/bin/env python3
"""
predict_params.py  —  CRAN SERVER ONLY
Deploy to: /home/mihoubrahma/cooja-sim/predict_params.py

Called via SSH by adaptive_monitor.py:
    python3 /home/mihoubrahma/cooja-sim/predict_params.py --kpis "..."

Output (stdout, one CSV line):
    path_loss_exponent,awgn_sigma,rssi_inflection_point,rx_sensitivity
    (rx_sensitivity is always -100.0 — fixed, not predicted)
"""

import argparse
import sys
import numpy as np

MODEL_PATH    = "/home/mihoubrahma/Calibration models/mlp11_model.pt"
X_SCALER_PATH = "/home/mihoubrahma/Calibration models/mlp11_x_scaler.pkl"
Y_SCALER_PATH = "/home/mihoubrahma/Calibration models/mlp11_y_scaler.pkl"

# Order matches TARGET_COLS in training notebook:
# [RSSI_INFLECTION_POINT, PATH_LOSS_EXPONENT, AWGN_SIGMA]

THROUGHPUT_PER_LOSS_MAX = 571.0  # training data ceiling — prevents explosion at loss≈0


def build_features(mean_rssi, std_rssi, min_rssi, loss_rate,
                   throughput, mean_delay, std_delay, std_loss, min_prr):
    """11-feature vector — exact same order as training FEATURE_COLS."""
    rssi_x_loss         = mean_rssi * loss_rate
    throughput_per_loss = min(throughput / (loss_rate + 1e-6), THROUGHPUT_PER_LOSS_MAX)
    return np.array([[
        mean_rssi, std_rssi, min_rssi,
        loss_rate, throughput,
        mean_delay, std_delay,
        std_loss, min_prr,
        rssi_x_loss,
        throughput_per_loss,
    ]])


def load_model():
    import torch
    import torch.nn as nn
    import joblib

    class MLP(nn.Module):
        def __init__(self, input_dim=11, output_dim=3):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(input_dim, 128),
                nn.BatchNorm1d(128),  nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(128, 256),
                nn.BatchNorm1d(256), nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(256, 512),
                nn.BatchNorm1d(512), nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(512, 256),
                nn.BatchNorm1d(256), nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(256, 128),
                nn.BatchNorm1d(128),  nn.ReLU(), nn.Dropout(0.1),
                nn.Linear(128, output_dim),
            )
        def forward(self, x):
            return self.network(x)

    model = MLP()
    model.load_state_dict(
        torch.load(MODEL_PATH, map_location="cpu"))
    model.eval()

    x_scaler = joblib.load(X_SCALER_PATH)
    y_scaler = joblib.load(Y_SCALER_PATH)
    return model, x_scaler, y_scaler


def predict(values):
    import torch
    features = build_features(*values)
    model, x_scaler, y_scaler = load_model()
    x_scaled = x_scaler.transform(features)
    with torch.no_grad():
        y_scaled = model(torch.FloatTensor(x_scaled)).numpy()
    return y_scaler.inverse_transform(y_scaled)[0]
    # returns [rssi_inflection, path_loss_exp, awgn_sigma]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kpis", required=True,
        help="9 comma-separated values: mean_rssi,std_rssi,min_rssi,"
             "loss_rate,throughput,mean_delay,std_delay,std_loss,min_prr")
    args = parser.parse_args()

    try:
        values = [float(v) for v in args.kpis.split(",")]
    except Exception as e:
        print(f"ERROR parsing KPIs: {e}", file=sys.stderr); sys.exit(1)

    if len(values) != 9:
        print(f"ERROR: expected 9 values, got {len(values)}", file=sys.stderr)
        sys.exit(1)

    try:
        params = predict(values)
    except Exception as e:
        print(f"ERROR prediction failed: {e}", file=sys.stderr); sys.exit(1)

    rssi_inflection = params[0]
    path_loss_exp   = params[1]
    awgn_sigma      = params[2]
    rx_sensitivity  = -100.0   # fixed

    # Output order matches what adaptive_monitor.py expects
    print(f"{path_loss_exp:.6f},{awgn_sigma:.6f},{rssi_inflection:.6f},{rx_sensitivity:.6f}")


if __name__ == "__main__":
    main()
