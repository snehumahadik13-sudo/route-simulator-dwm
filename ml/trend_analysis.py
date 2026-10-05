"""
ml/trend_analysis.py
Trend analysis: peak emergency hours, accident trends, weather effects,
traffic congestion patterns, and emergency response patterns.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_trend_analysis():
    print("\n" + "="*60)
    print("TREND ANALYSIS — Temporal & Contextual Patterns")
    print("="*60)

    from ml.db_loader import load_accident_data, load_ems_data, load_weather_data, load_traffic_data

    results = {}

    # ── 1. Peak Emergency Hours ────────────────────────────────────────────
    print("\n[1/5] Peak Emergency Hours (EMS)...")
    try:
        df_ems = load_ems_data()
        if "hour_24" in df_ems.columns:
            hour_col = "hour_24"
        elif "timestamp" in df_ems.columns:
            df_ems["hour_24"] = pd.to_datetime(df_ems["timestamp"], errors="coerce").dt.hour
            hour_col = "hour_24"
        else:
            hour_col = None

        if hour_col:
            hourly_ems = df_ems.groupby(hour_col).size().reset_index(name="ems_count")
            hourly_ems = hourly_ems.sort_values(hour_col)
            peak_hours = hourly_ems.nlargest(5, "ems_count")
            print(f"  Top 5 EMS peak hours:")
            for _, row in peak_hours.iterrows():
                print(f"    {int(row[hour_col]):02d}:00  →  {int(row['ems_count']):,} calls")
            results["peak_ems_hours"] = hourly_ems.to_dict(orient="records")
            hourly_ems.to_csv(OUTPUT_DIR / "trend_peak_ems_hours.csv", index=False)
    except Exception as e:
        print(f"  EMS trend failed: {e}")

    # ── 2. Accident Trends by Hour and Day ────────────────────────────────
    print("\n[2/5] Accident Patterns (Hour + Day of Week)...")
    try:
        df_acc = load_accident_data()
        acc_hour_col = "hour_24" if "hour_24" in df_acc.columns else None
        if acc_hour_col is None and "hour" in df_acc.columns:
            df_acc["hour_24"] = pd.to_numeric(df_acc["hour"], errors="coerce")
            acc_hour_col = "hour_24"

        if acc_hour_col:
            hourly_acc = df_acc.groupby(acc_hour_col).agg(
                accident_count=("accident_severity" if "accident_severity" in df_acc.columns else "city", "count"),
            ).reset_index()
            hourly_acc = hourly_acc.sort_values(acc_hour_col)
            peak_acc = hourly_acc.nlargest(3, "accident_count")
            print(f"  Top accident hours: {peak_acc[acc_hour_col].tolist()}")
            results["hourly_accidents"] = hourly_acc.to_dict(orient="records")
            hourly_acc.to_csv(OUTPUT_DIR / "trend_hourly_accidents.csv", index=False)

        # Severity breakdown
        if "accident_severity" in df_acc.columns:
            sev_dist = df_acc["accident_severity"].value_counts().to_dict()
            print(f"  Severity distribution: {sev_dist}")
            results["severity_distribution"] = sev_dist

        # City-wise accidents
        city_col = "city"
        if city_col in df_acc.columns:
            city_acc = df_acc.groupby(city_col).size().reset_index(name="count").sort_values("count", ascending=False)
            print(f"  Top cities: {city_acc.head(5).to_dict(orient='records')}")
            results["accidents_by_city"] = city_acc.to_dict(orient="records")
            city_acc.to_csv(OUTPUT_DIR / "trend_accidents_by_city.csv", index=False)
    except Exception as e:
        print(f"  Accident trend failed: {e}")

    # ── 3. Weather Effects on Accidents ───────────────────────────────────
    print("\n[3/5] Weather Effects on Accidents...")
    try:
        df_acc2 = load_accident_data()
        if "weather" in df_acc2.columns and "risk_score" in df_acc2.columns:
            df_acc2["risk_score"] = pd.to_numeric(df_acc2["risk_score"], errors="coerce")
            df_acc2["casualties"] = pd.to_numeric(df_acc2.get("casualties", 0), errors="coerce").fillna(0)
            weather_agg = df_acc2.groupby("weather").agg(
                accident_count=("weather","count"),
                avg_risk=("risk_score","mean"),
                total_casualties=("casualties","sum"),
            ).reset_index().sort_values("accident_count", ascending=False)
            print("  Weather → Accident Impact:")
            for _, row in weather_agg.iterrows():
                print(f"    {row['weather']:<15} accidents={int(row['accident_count']):>5}  "
                      f"avg_risk={row['avg_risk']:.3f}  casualties={int(row['total_casualties'])}")
            results["weather_accident_impact"] = weather_agg.to_dict(orient="records")
            weather_agg.to_csv(OUTPUT_DIR / "trend_weather_accidents.csv", index=False)
    except Exception as e:
        print(f"  Weather effect analysis failed: {e}")

    # ── 4. Traffic Congestion Patterns ────────────────────────────────────
    print("\n[4/5] Traffic Congestion Patterns...")
    try:
        df_traffic = load_traffic_data(limit=30000)
        label_col = "congestion_label" if "congestion_label" in df_traffic.columns else "label"
        if label_col in df_traffic.columns:
            label_dist = df_traffic[label_col].value_counts()
            print(f"  Congestion label distribution:")
            for label, cnt in label_dist.items():
                pct = cnt / len(df_traffic) * 100
                bar = "█" * int(pct / 2)
                print(f"    {label:<20} {cnt:>7,} ({pct:.1f}%) {bar}")
            results["congestion_distribution"] = label_dist.to_dict()

        # Speed distribution
        spd_col = "avg_speed_kmph"
        if spd_col in df_traffic.columns:
            df_traffic[spd_col] = pd.to_numeric(df_traffic[spd_col], errors="coerce")
            speed_buckets = pd.cut(df_traffic[spd_col].dropna(),
                                   bins=[0,20,40,60,80,200],
                                   labels=["<20","20-40","40-60","60-80",">80"])
            speed_dist = speed_buckets.value_counts().to_dict()
            print(f"\n  Speed distribution (km/h): {speed_dist}")
            results["speed_distribution"] = {str(k): int(v) for k,v in speed_dist.items()}
    except Exception as e:
        print(f"  Traffic trend failed: {e}")

    # ── 5. Emergency Response Patterns ────────────────────────────────────
    print("\n[5/5] Emergency Response Patterns...")
    try:
        df_ems2 = load_ems_data()
        if "triage_priority" in df_ems2.columns:
            triage_dist = df_ems2["triage_priority"].value_counts()
            print(f"  Triage distribution: {triage_dist.to_dict()}")
            results["triage_distribution"] = triage_dist.to_dict()

        if "condition" in df_ems2.columns:
            cond_dist = df_ems2["condition"].value_counts().head(10)
            print(f"  Top 10 medical conditions: {cond_dist.to_dict()}")
            results["condition_distribution"] = cond_dist.to_dict()

        if "clinical_urgency_score" in df_ems2.columns:
            df_ems2["clinical_urgency_score"] = pd.to_numeric(df_ems2["clinical_urgency_score"], errors="coerce")
            urgency_stats = {
                "mean": round(float(df_ems2["clinical_urgency_score"].mean()), 3),
                "median": round(float(df_ems2["clinical_urgency_score"].median()), 3),
                "high_urgency_pct": round(float((df_ems2["clinical_urgency_score"] >= 7).mean() * 100), 2)
            }
            print(f"  Urgency score stats: {urgency_stats}")
            results["urgency_stats"] = urgency_stats
    except Exception as e:
        print(f"  EMS response pattern failed: {e}")

    # ── Save all results ───────────────────────────────────────────────────
    # Convert non-serializable types
    def convert(obj):
        if isinstance(obj, (np.integer, np.int64)): return int(obj)
        if isinstance(obj, (np.floating, np.float64)): return float(obj)
        return str(obj)

    with open(OUTPUT_DIR / "trend_analysis.json", "w") as f:
        json.dump(results, f, indent=2, default=convert)
    print(f"\n✓ Trend analysis complete. Results: {OUTPUT_DIR}/trend_analysis.json")
    return results


if __name__ == "__main__":
    run_trend_analysis()
