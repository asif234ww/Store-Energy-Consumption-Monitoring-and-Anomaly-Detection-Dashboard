# Energy Data Analytics: two portfolio projects

## 1. Store Energy Consumption Monitoring and Anomaly Detection
Dataset: ASHRAE Great Energy Predictor III (Kaggle). Files: `train.csv`, `building_metadata.csv`.
Run: `python energy_dashboard_project.py --train train.csv --meta building_metadata.csv`
Output folder: `output_energy/` (cleaned daily data, EUI benchmark, anomalies, forecast backtest, 3 charts, summary.txt)

## 2. Solar PV Performance Monitoring and Reporting
Dataset: "Solar Power Generation Data" (Kaggle), Plant 1 files.
Run: `python solar_pv_project.py --gen Plant_1_Generation_Data.csv --weather Plant_1_Weather_Sensor_Data.csv`
Output folder: `output_solar/` (daily yield by inverter, inverter summary, 3 charts, summary.txt)

Needs: Python 3, pandas, numpy, matplotlib (`pip install pandas numpy matplotlib`).

## IMPORTANT: demo vs real results
`--demo` runs on SYNTHETIC data to prove the code works. The `demo_output/` folder is from that.
Do NOT put demo numbers on your resume. Run both scripts on the real Kaggle data, then use the numbers in each `summary.txt`
for [X] and [Y]:
- Energy: [X] = "Anomalous days flagged", [Y] = excess kWh (or convert to cost with your own tariff).
- Solar: [X] = number of underperforming inverters, [Y] = estimated lost output in kWh.

## Before you claim "Power BI" on the resume
The scripts create Power BI-ready CSV files, but they do not create the dashboard. Open Power BI Desktop, import the CSV files
(`daily_consumption.csv`, `eui_benchmark.csv`, `anomalies.csv`, `inverter_summary.csv`, `daily_yield_by_inverter.csv`),
and build the visuals yourself, or remove "Power BI" from the project line.

## Assumptions to check and be ready to explain in an interview
- Emission factor 0.71 kg CO2e/kWh is a placeholder. Look up the latest published factor for your region.
- Anomaly = robust z-score above 3.5 on daily use versus a 28-day rolling median.
- Underperforming inverter = mean daily yield below 90% of the fleet median.
- Forecast = average of the same weekday over the previous 8 weeks (simple baseline, backtested on 28 days).
- Real-data column names are written from memory of the Kaggle files. If a run fails with a KeyError, compare the names in your CSV with the script.
