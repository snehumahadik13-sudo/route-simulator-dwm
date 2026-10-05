"""
ml/clustering.py
K-Means clustering of road segments using aggregate traffic telemetry metrics.
Uses genuine S001-S500 segment IDs. No fabricated data.
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)

CLUSTER_LABELS = {
    0: "Free-Flow",
    1: "Moderate Congestion",
    2: "High Congestion",
    3: "Gridlock / Critical",
    4: "Low-Traffic Night",
}


def run_kmeans(n_clusters: int = 4):
    print("\n" + "="*60)
    print("K-MEANS CLUSTERING — Road Segment Traffic Profiles")
    print("="*60)

    from ml.db_loader import load_segment_stats
    df = load_segment_stats()
    print(f"Loaded {len(df):,} road segments for clustering.")

    if df.empty:
        print("No segment data available.")
        return {}

    # ── Feature selection ──────────────────────────────────────────────────
    feature_cols = [
        "mean_speed", "mean_density", "mean_wait", "mean_occupancy",
        "mean_congestion", "mean_incidents", "mean_visibility", "mean_rain",
    ]
    feature_cols = [c for c in feature_cols if c in df.columns]
    X_raw = df[feature_cols].fillna(0)

    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score, davies_bouldin_score

    scaler = StandardScaler()
    X = scaler.fit_transform(X_raw)

    # ── Elbow method to pick best k ────────────────────────────────────────
    inertias = []
    ks = range(2, min(8, len(df)))
    for k in ks:
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        km.fit(X)
        inertias.append(km.inertia_)

    # Use elbow or provided n_clusters
    best_k = n_clusters
    if len(inertias) > 2:
        diffs = np.diff(inertias)
        diffs2 = np.diff(diffs)
        elbow_idx = int(np.argmax(diffs2)) + 2
        best_k = min(max(elbow_idx, 2), n_clusters)

    print(f"Running K-Means with k={best_k} clusters on {len(feature_cols)} features...")
    km = KMeans(n_clusters=best_k, random_state=42, n_init=20, max_iter=500)
    labels = km.fit_predict(X)
    df["cluster"] = labels

    sil_score = float(silhouette_score(X, labels)) if len(set(labels)) > 1 else 0.0
    db_score  = float(davies_bouldin_score(X, labels)) if len(set(labels)) > 1 else 0.0
    print(f"Silhouette Score: {sil_score:.4f}  (higher=better, range -1..1)")
    print(f"Davies-Bouldin:   {db_score:.4f}  (lower=better)")

    # ── Cluster profiles ───────────────────────────────────────────────────
    print("\nCluster Profiles:")
    print("-"*80)
    cluster_profiles = {}
    for c in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == c]
        profile = {col: round(float(sub[col].mean()), 3) for col in feature_cols if col in sub.columns}
        profile["segment_count"] = int(len(sub))
        segments = sorted(sub["road_segment_id"].tolist()) if "road_segment_id" in sub.columns else []
        profile["segments_sample"] = segments[:10]

        # Auto-label based on speed and congestion
        spd = profile.get("mean_speed", 0)
        cong = profile.get("mean_congestion", 0)
        if spd > 60:
            label = "Free-Flow"
        elif spd > 40:
            label = "Moderate Traffic"
        elif spd > 20:
            label = "High Congestion"
        else:
            label = "Gridlock / Critical"
        profile["label"] = label

        cluster_profiles[int(c)] = profile
        print(f"\n  Cluster {c} — {label} ({len(sub)} segments)")
        print(f"    Speed: {profile.get('mean_speed','?'):.1f} km/h  "
              f"Density: {profile.get('mean_density','?'):.1f} veh/km  "
              f"Wait: {profile.get('mean_wait','?'):.1f} s  "
              f"Congestion: {profile.get('mean_congestion','?'):.4f}")
        if segments:
            print(f"    Segments (sample): {', '.join(segments[:8])}{'...' if len(segments)>8 else ''}")

    # ── Save results ───────────────────────────────────────────────────────
    df["cluster_label"] = df["cluster"].map(lambda c: cluster_profiles[c]["label"])
    segment_result = df[["road_segment_id","cluster","cluster_label"] + feature_cols].copy() if "road_segment_id" in df.columns else df.copy()
    segment_result.to_csv(OUTPUT_DIR / "clustering_segments.csv", index=False)

    summary = {
        "k": best_k,
        "silhouette_score": round(sil_score, 4),
        "davies_bouldin_score": round(db_score, 4),
        "features_used": feature_cols,
        "clusters": cluster_profiles
    }
    with open(OUTPUT_DIR / "clustering_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n✓ Clustering results saved to: {OUTPUT_DIR}")
    return summary


if __name__ == "__main__":
    run_kmeans()
