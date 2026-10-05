"""
ml/anomaly_detection.py
Detects anomalous traffic and EMS patterns using Isolation Forest + Z-score.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_anomaly_detection(contamination: float = 0.05):
    print("\n" + "="*60)
    print("ANOMALY DETECTION — Isolation Forest")
    print("="*60)

    from ml.db_loader import load_traffic_data, load_ems_data
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    results = {}

    # ── Traffic Anomalies ──────────────────────────────────────────────────
    print("\n[1/2] Traffic Telemetry Anomalies...")
    try:
        df_traffic = load_traffic_data(limit=50000)
        traffic_features = [
            "avg_speed_kmph", "density_veh_per_km", "avg_wait_time_s",
            "occupancy_pct", "flow_veh_per_hr", "congestion_pressure",
            "incident_num", "visibility_km", "rain_intensity_mmph"
        ]
        # Use float conversion
        traffic_features = [c for c in traffic_features if c in df_traffic.columns]
        X_traffic = df_traffic[traffic_features].copy()
        for col in traffic_features:
            X_traffic[col] = pd.to_numeric(X_traffic[col], errors="coerce")
        X_traffic = X_traffic.fillna(0)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_traffic)

        iso = IsolationForest(contamination=contamination, random_state=42, n_jobs=-1)
        preds = iso.fit_predict(X_scaled)
        scores = iso.score_samples(X_scaled)

        df_traffic["anomaly"] = (preds == -1).astype(int)
        df_traffic["anomaly_score"] = scores

        n_anomalies = int((preds == -1).sum())
        pct = n_anomalies / len(preds) * 100

        print(f"  Total records analyzed: {len(preds):,}")
        print(f"  Anomalies detected: {n_anomalies:,} ({pct:.2f}%)")

        # Characterize anomalies
        anomaly_df = df_traffic[df_traffic["anomaly"] == 1].copy()
        normal_df  = df_traffic[df_traffic["anomaly"] == 0].copy()

        print("\n  Anomaly vs Normal — Mean Feature Comparison:")
        comparison = {}
        for feat in traffic_features:
            try:
                a_mean = float(anomaly_df[feat].mean())
                n_mean = float(normal_df[feat].mean())
                ratio  = (a_mean / n_mean) if n_mean != 0 else 0
                comparison[feat] = {"anomaly_mean": round(a_mean,3), "normal_mean": round(n_mean,3), "ratio": round(ratio,3)}
                print(f"    {feat:<35} anomaly={a_mean:>8.3f}  normal={n_mean:>8.3f}  ratio={ratio:.2f}")
            except Exception:
                pass

        # Save top anomalies
        top_anomalies = anomaly_df.nsmallest(100, "anomaly_score")
        cols_to_save = ["road_segment_id"] + traffic_features + ["anomaly_score"] if "road_segment_id" in top_anomalies.columns else traffic_features + ["anomaly_score"]
        top_anomalies[cols_to_save].to_csv(OUTPUT_DIR / "traffic_anomalies.csv", index=False)

        results["traffic"] = {
            "total_records": len(preds),
            "anomalies_detected": n_anomalies,
            "anomaly_pct": round(pct, 3),
            "feature_comparison": comparison
        }
        print(f"  ✓ Top traffic anomalies saved to ml_results/traffic_anomalies.csv")

    except Exception as e:
        print(f"  Traffic anomaly detection failed: {e}")
        results["traffic"] = {"error": str(e)}

    # ── EMS Anomalies ──────────────────────────────────────────────────────
    print("\n[2/2] EMS Event Anomalies...")
    try:
        df_ems = load_ems_data()
        ems_features = ["patient_age", "sbp", "heart_rate", "spo2", "gcs", "clinical_urgency_score"]
        ems_features = [c for c in ems_features if c in df_ems.columns]

        if not ems_features:
            # staging fallback
            df_ems = df_ems.rename(columns={"age": "patient_age"})
            ems_features = [c for c in ["patient_age","sbp","heart_rate","spo2","gcs"] if c in df_ems.columns]

        X_ems = df_ems[ems_features].copy()
        for col in ems_features:
            X_ems[col] = pd.to_numeric(X_ems[col], errors="coerce")
        X_ems = X_ems.fillna(X_ems.median())

        scaler2 = StandardScaler()
        X_ems_scaled = scaler2.fit_transform(X_ems)

        iso2 = IsolationForest(contamination=contamination, random_state=42)
        preds2 = iso2.fit_predict(X_ems_scaled)
        scores2 = iso2.score_samples(X_ems_scaled)

        df_ems["anomaly"] = (preds2 == -1).astype(int)
        df_ems["anomaly_score"] = scores2

        n_ems_anomalies = int((preds2 == -1).sum())
        print(f"  Total EMS records: {len(preds2):,}")
        print(f"  Anomalies detected: {n_ems_anomalies:,} ({n_ems_anomalies/len(preds2)*100:.2f}%)")

        # Characteristics of anomalous EMS events
        anom_ems = df_ems[df_ems["anomaly"] == 1]
        if "triage_priority" in anom_ems.columns:
            print(f"  Triage distribution in anomalies:")
            print(f"  {anom_ems['triage_priority'].value_counts().to_dict()}")

        top_ems = anom_ems.nsmallest(200, "anomaly_score")
        top_ems.to_csv(OUTPUT_DIR / "ems_anomalies.csv", index=False)

        results["ems"] = {
            "total_records": len(preds2),
            "anomalies_detected": n_ems_anomalies,
            "anomaly_pct": round(n_ems_anomalies/len(preds2)*100, 3)
        }
        print(f"  ✓ Top EMS anomalies saved to ml_results/ems_anomalies.csv")

    except Exception as e:
        print(f"  EMS anomaly detection failed: {e}")
        results["ems"] = {"error": str(e)}

    # Save overall results
    with open(OUTPUT_DIR / "anomaly_detection.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Anomaly detection complete. Results: {OUTPUT_DIR}/anomaly_detection.json")
    return results


if __name__ == "__main__":
    run_anomaly_detection()
