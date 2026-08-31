# Calibration

Calibrating the Cooja network simulator's radio model against real hardware
measurements from the [FIT IoT-LAB](https://www.iot-lab.info/) testbed
(Grenoble site, M3 nodes), so that Cooja simulations reproduce real-world
RSSI, packet loss, and delay behavior.

## Approach

1. Run the same firmware on FIT IoT-LAB hardware and in Cooja, under matching
   traffic patterns (single link, many-to-one, and interference scenarios).
2. Compare the resulting KPIs (RSSI, loss rate, delay) between testbed and
   simulation.
3. Train a model (`calibration-model/`) that predicts the Cooja radio
   parameters (path loss exponent, AWGN sigma, RSSI inflection point) that
   make simulation match a given testbed run.
4. Use that model in an adaptive pipeline that re-calibrates Cooja parameters
   as traffic conditions change, and explore parameter sensitivity through
   "what-if" sweeps.

## Repository layout

| Path | Contents |
|---|---|
| `contiki-firmware/` | Custom Contiki-NG firmware (source + Makefile) run on both FIT IoT-LAB and Cooja: `radio-link-quality` (single sender/receiver) and `many-to-one-traffic-simu` (many-to-one traffic). |
| `firmwares/` | Additional sender/interferer firmware variants used in Cooja-only experiments. |
| `scripts/` | Entry points that launch FIT IoT-LAB and/or Cooja experiments and compare metrics: `run_unified.sh`, `run_cooja_only.sh`, `run_fit_only.sh`, `run_interference_experiment.sh`, `submit_dataset.sh`. |
| `templates/` | Cooja `.csc` simulation templates. |
| `tools/` | Log parsing, KPI extraction, plotting, and analysis scripts shared by the run scripts. |
| `dataset/`, `parameter-combination/` | Testbed-vs-simulation datasets and the parameter grids they were generated from. |
| `calibration-model/` | Notebooks and trained MLP models (PyTorch) that predict Cooja radio parameters from testbed KPIs, plus the training datasets. |
| `what-if/`, `scenarios-setup/` | Parameter-sensitivity sweep scripts/datasets and the per-scenario node layouts they use. |
| `adaptive-pipeline/` | The adaptive calibration pipeline: `predict_params.py` predicts parameters from live KPIs, `adaptive_monitor.py` monitors for drift and re-triggers calibration, `app.py` is a small web UI to run/inspect it. |

## Reproducing an experiment

```bash
# Build and run the radio-link-quality firmware in Cooja
cd contiki-firmware/radio-link-quality
make TARGET=cooja

# From the repo root, run a matched FIT IoT-LAB + Cooja experiment
./scripts/run_unified.sh -u <iot-lab-username> -n 3+4+5 -r 2 -d 5
```

See the `-h`/usage comments at the top of each `scripts/run_*.sh` script for
the full option list.

## Note on the adaptive pipeline

`adaptive-pipeline/predict_params.py`, `adaptive_monitor.py`, and `app.py`
were built to run on a specific compute server (paths and model locations
are hardcoded, e.g. `predict_params.py` expects the trained models under
`/home/<user>/Calibration models/`). To run them elsewhere, point those
paths at your local `calibration-model/` directory.
