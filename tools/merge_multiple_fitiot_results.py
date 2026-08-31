import os, csv, statistics

scenario01_results_dirs = [
    "/home/rahma/Desktop/unified_workflow/results/Scenario01/fitiot_ch11_tx0_20260415_190853/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario01/fitiot_ch11_tx0_20260417_113250/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario01/fitiot_ch11_tx0_20260417_123838/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario01/fitiot_ch11_tx0_20260417_150353/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario01/fitiot_ch11_tx0_20260417_162216/fitiot",
]
scenario02_results_dirs = [
    "/home/rahma/Desktop/unified_workflow/results/Scenario02/fitiot_ch11_tx0_20260422_113644/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario02/fitiot_ch11_tx0_20260422_142247/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario02/fitiot_ch11_tx0_20260422_152524/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario02/fitiot_ch11_tx0_20260423_095242/fitiot",
    "/home/rahma/Desktop/unified_workflow/results/Scenario02/fitiot_ch11_tx0_20260423_105452/fitiot",
]

all_delay, all_lossrate, all_throughput, all_rssi_dbm = [], [], [], []

for d in scenario02_results_dirs:
    with open(os.path.join(d, "metrics.csv")) as f:
        row = next(csv.DictReader(f))
    all_delay.append(float(row["delay"]))
    all_lossrate.append(float(row["lossrate"]))
    all_throughput.append(float(row["throughput"]))
    all_rssi_dbm.append(float(row["rssi_dbm"]))
baseline = {
    "delay_mean":      statistics.mean(all_delay),
    "delay_std":       statistics.stdev(all_delay),
    "lossrate_mean":   statistics.mean(all_lossrate),
    "lossrate_std":    statistics.stdev(all_lossrate),
    "throughput_mean": statistics.mean(all_throughput),
    "throughput_std":  statistics.stdev(all_throughput),
    "rssi_dbm_mean": statistics.mean(all_rssi_dbm),
    "rssi_dbm_std":  statistics.stdev(all_rssi_dbm),
}

print("Baseline:")
for k, v in baseline.items():
    print(f"  {k}: {v:.4f}")

# Save as a single baseline CSV
with open("results/fitiotch11_tx0_min60_baseline/baseline_metrics02.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["metric", "mean", "std"])
    writer.writerow(["delay",      baseline["delay_mean"],      baseline["delay_std"]])
    writer.writerow(["lossrate",   baseline["lossrate_mean"],   baseline["lossrate_std"]])
    writer.writerow(["throughput", baseline["throughput_mean"], baseline["throughput_std"]])
    writer.writerow(["rssi_dbm", baseline["rssi_dbm_mean"], baseline["rssi_dbm_std"]])

print("\n✓ Saved to results/fitiotch11_tx0_min60_baseline/baseline_metricsX.csv")