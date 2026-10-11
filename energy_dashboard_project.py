import argparse, os
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SQFT_TO_M2 = 0.092903
EMISSION_FACTOR = 0.71
EUI_PLAUSIBLE_MAX = 1000
Z_LIMIT = 3.5


def load_demo(seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-01-01", "2016-12-31 23:00", freq="h")
    meta, rows = [], []
    for b in range(1, 13):
        sqft = int(rng.integers(30000, 250000))
        meta.append({"building_id": b, "primary_use": "Retail", "square_feet": sqft})
        base = sqft * 0.0012
        hour = np.where((idx.hour >= 9) & (idx.hour <= 21), 1.0, 0.45)
        season = 1 + 0.25 * np.sin((np.asarray(idx.dayofyear) - 150) / 365 * 2 * np.pi)
        y = np.asarray(base * hour * season * rng.normal(1, 0.05, len(idx)), dtype=float)
        for _ in range(3):  # injected spikes
            s = int(rng.integers(0, len(idx) - 48)); y[s:s + 36] *= rng.uniform(1.8, 2.5)
        y[rng.choice(len(idx), 60, replace=False)] = np.nan   # missing readings
        y[rng.choice(len(idx), 5, replace=False)] = -1        # meter errors
        rows.append(pd.DataFrame({"building_id": b, "meter": 0, "timestamp": idx, "meter_reading": y}))
    return pd.concat(rows, ignore_index=True), pd.DataFrame(meta)


def load_real(train, meta):
    """ASHRAE-style long format: train.csv with building_id, meter, timestamp, meter_reading."""
    df = pd.read_csv(train, parse_dates=["timestamp"])
    df = df[df.meter == 0]
    m = pd.read_csv(meta)
    keep = m[m.primary_use.isin(["Retail", "Office", "Education"])].building_id.unique()[:40]
    return df[df.building_id.isin(keep)], m[m.building_id.isin(keep)]


def load_bdg2(elec, metadata, n=40):
    """Building Data Genome Project 2 (free, no competition): electricity.csv is WIDE (timestamp + one column per building)."""
    m = pd.read_csv(metadata)
    use_col = next((c for c in m.columns if "primary" in c.lower() and "usage" in c.lower()), None)
    area_col = "sqm" if "sqm" in m.columns else next(c for c in m.columns if "sq" in c.lower())
    e = pd.read_csv(elec, parse_dates=["timestamp"])
    m = m[m.building_id.isin(e.columns)].dropna(subset=[area_col])
    if use_col:
        pref = m[m[use_col].isin(["Retail", "Office", "Education"])]
        m = pref if len(pref) >= 5 else m
    m = m.head(n).copy()
    m["square_feet"] = m[area_col] / SQFT_TO_M2 if area_col == "sqm" else m[area_col]
    m["primary_use"] = m[use_col] if use_col else "Unknown"
    long = e[["timestamp"] + list(m.building_id)].melt("timestamp", var_name="building_id", value_name="meter_reading")
    long["meter"] = 0
    return long, m[["building_id", "primary_use", "square_feet"]]


def clean(df):
    log = {"rows_in": len(df), "missing": int(df.meter_reading.isna().sum()),
           "negative": int((df.meter_reading < 0).sum())}
    df = df.copy()
    df.loc[df.meter_reading < 0, "meter_reading"] = np.nan
    df = df.sort_values(["building_id", "timestamp"])
    df["meter_reading"] = df.groupby("building_id")["meter_reading"].transform(
        lambda s: s.interpolate(limit=6, limit_direction="both"))
    log["unfilled_dropped"] = int(df.meter_reading.isna().sum())
    return df.dropna(subset=["meter_reading"]), log


def daily(df):
    d = (df.set_index("timestamp").groupby("building_id")["meter_reading"]
           .resample("D").sum().reset_index().rename(columns={"meter_reading": "kwh"}))
    return d


def eui_table(d, meta):
    t = d.groupby("building_id").agg(total_kwh=("kwh", "sum"), days_with_data=("kwh", lambda x: int((x > 0).sum()))).reset_index()
    t["annual_kwh"] = t.total_kwh / t.days_with_data.clip(lower=1) * 365
    t = t.merge(meta, on="building_id")
    t["EUI_kwh_m2"] = t.annual_kwh / (t.square_feet * SQFT_TO_M2)
    t["emissions_kgCO2e"] = t.annual_kwh * EMISSION_FACTOR
    t["check_data"] = t.EUI_kwh_m2 > EUI_PLAUSIBLE_MAX     # implausible EUI = likely wrong area or meter data
    med = t.loc[~t.check_data, "EUI_kwh_m2"].median()
    t["vs_median_pct"] = (t.EUI_kwh_m2 / med - 1) * 100
    return t.sort_values("EUI_kwh_m2", ascending=False)


def anomalies(d):
    out = []
    for b, g in d.groupby("building_id"):
        g = g.copy()
        med = g.kwh.rolling(28, min_periods=14, center=True).median()
        mad = (g.kwh - med).abs().rolling(28, min_periods=14, center=True).median().replace(0, np.nan)
        g["z"] = 0.6745 * (g.kwh - med) / mad
        g["expected_kwh"] = med
        out.append(g[g.z > Z_LIMIT])
    a = pd.concat(out) if out else pd.DataFrame()
    a["excess_kwh"] = a.kwh - a.expected_kwh
    return a


def forecast_backtest(d, horizon=28):
    """Seasonal-naive by weekday: average of the same weekday over the 8 weeks before the test window."""
    tot = d.groupby("timestamp").kwh.sum().asfreq("D")
    train, test = tot[:-horizon], tot[-horizon:]
    last8 = train[-56:]
    prof = last8.groupby(last8.index.dayofweek).mean()
    pred = pd.Series([prof[i.dayofweek] for i in test.index], index=test.index)
    mape = float((abs(test - pred) / test).mean() * 100)
    return test, pred, mape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train"); ap.add_argument("--meta"); ap.add_argument("--demo", action="store_true")
    ap.add_argument("--electricity"); ap.add_argument("--metadata")
    a = ap.parse_args()
    if a.demo: df, meta = load_demo()
    elif a.electricity: df, meta = load_bdg2(a.electricity, a.metadata)
    else: df, meta = load_real(a.train, a.meta)
    out = "output_energy"; os.makedirs(out, exist_ok=True)
    df, log = clean(df); d = daily(df)
    eui = eui_table(d, meta); an = anomalies(d); test, pred, mape = forecast_backtest(d)
    d.to_csv(f"{out}/daily_consumption.csv", index=False)
    eui.to_csv(f"{out}/eui_benchmark.csv", index=False)
    an.to_csv(f"{out}/anomalies.csv", index=False)
    pd.DataFrame({"date": test.index, "actual_kwh": test.values, "forecast_kwh": pred.values}).to_csv(f"{out}/forecast_backtest.csv", index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    ok = eui[~eui.check_data].head(25)
    ax.bar(ok.building_id.astype(str).str[-12:], ok.EUI_kwh_m2, color="#1F3864"); plt.xticks(rotation=75, fontsize=7)
    ax.axhline(eui.loc[~eui.check_data, "EUI_kwh_m2"].median(), color="red", ls="--", label="Median")
    ax.set(title="Energy Use Intensity by building", xlabel="Building", ylabel="kWh/m² per year"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{out}/eui_benchmark.png", dpi=130); plt.close(fig)

    b0 = an.building_id.value_counts().index[0] if len(an) else d.building_id.iloc[0]
    g = d[d.building_id == b0]; fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(g.timestamp, g.kwh, color="#1F3864", lw=1)
    ga = an[an.building_id == b0]; ax.scatter(ga.timestamp, ga.kwh, color="red", zorder=3, label="Anomaly")
    ax.set(title=f"Daily electricity use, building {b0}", ylabel="kWh"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{out}/daily_trend_anomalies.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4)); ax.plot(test.index, test, label="Actual"); ax.plot(pred.index, pred, "--", label="Forecast")
    ax.set(title=f"28-day backtest (MAPE {mape:.1f}%)", ylabel="Total kWh/day"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{out}/forecast_backtest.png", dpi=130); plt.close(fig)

    top = eui[~eui.check_data].iloc[0]
    summary = [f"Mode: {'DEMO (synthetic data)' if a.demo else 'REAL data'}",
               f"Rows read: {log['rows_in']:,} | missing: {log['missing']:,} | negative/meter errors: {log['negative']:,} | dropped after cleaning: {log['unfilled_dropped']:,}",
               f"Buildings analysed: {eui.shape[0]}",
               f"Highest plausible EUI: building {top.building_id} at {top.EUI_kwh_m2:.0f} kWh/m²/year ({top.vs_median_pct:+.0f}% vs median)",
               f"Buildings flagged for a data check (EUI > {EUI_PLAUSIBLE_MAX}): {int(eui.check_data.sum())}",
               f"Total emissions: {eui.emissions_kgCO2e.sum()/1000:,.0f} tCO2e (factor {EMISSION_FACTOR} kg/kWh, assumption)",
               f"Anomalous days flagged: {len(an)} | excess consumption: {an.excess_kwh.sum():,.0f} kWh",
               f"Forecast backtest MAPE (28 days): {mape:.1f}%"]
    open(f"{out}/summary.txt", "w", encoding="utf-8").write("\n".join(summary)); print("\n".join(summary))


if __name__ == "__main__":
    main()