# Calibration

Calibrating the Cooja network simulator's radio model against real hardware
measurements from the [FIT IoT-LAB](https://www.iot-lab.info/) testbed
(Grenoble site, M3 nodes), so that Cooja simulations reproduce real-world
RSSI, packet loss, and delay behavior.

## Approach

1. Run the same firmware on FIT IoT-LAB hardware and in Cooja, under matching
   traffic patterns (single link and interference scenarios).
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
| `contiki-firmware/` | Firmware source to drop into your own Contiki-NG checkout — not a buildable-in-place tree (see below). `Cooja/` is the sender/receiver pair run inside Cooja; `FitIot-Lab/` holds the sender variants (TX-power phases, interferer, best-known-config) flashed on real FIT IoT-LAB nodes. |
| `scripts/` | Entry points that launch FIT IoT-LAB and/or Cooja experiments and compare metrics: `run_unified.sh`, `run_cooja_only.sh`, `run_fit_only.sh`, `run_interference_experiment.sh`, `submit_dataset.sh`. |
| `templates/` | Cooja `.csc` simulation templates. |
| `tools/` | Log parsing, KPI extraction, plotting, and analysis scripts shared by the run scripts, plus `run_one_sim.py` (the per-combination worker `submit_dataset.sh` submits to SLURM). |
| `datasets/` | Testbed-vs-simulation datasets. |
| `parameter-combination/` | `combinations.csv` — the parameter grid `submit_dataset.sh` sweeps over — and `summary.txt` describing it. `generate_combinations.py` (re)produces the full clean grid from the same value lists, for extending the study; see the comment at the top of that file for why it isn't a byte-identical replay of the current `combinations.csv`. |
| `calibration-model/` | Notebooks and trained MLP models (PyTorch) that predict Cooja radio parameters from testbed KPIs, plus the training datasets. |
| `what-if/`, `scenarios-setup/` | Parameter-sensitivity sweep scripts/datasets and the per-scenario node layouts they use. |
| `adaptive-pipeline/` | The adaptive calibration pipeline: `predict_params.py` predicts parameters from live KPIs, `adaptive_monitor.py` monitors for drift and re-triggers calibration, `app.py` is a small web UI to run/inspect it. |

## Reproducing an experiment

`contiki-firmware/` holds source files, not a ready-to-build example: Contiki-NG
expects firmware under its own `examples/` tree, and FIT IoT-LAB expects its own
profile/experiment setup. Copy the files in first, then build:

```bash
# Cooja: copy into your own Contiki-NG checkout and build there
cp -r contiki-firmware/Cooja ~/contiki-ng/examples/radio-link-quality
cd ~/contiki-ng/examples/radio-link-quality && make TARGET=cooja

# FIT IoT-LAB: copy the sender variant you need into your own profile/example
# directory before compiling for TARGET=iotlab-m3 (see scripts/run_interference_experiment.sh
# for how sender variants get uploaded and compiled on the FIT IoT-LAB frontend)

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
