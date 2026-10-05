"""
route_engine.py
Emergency Route Intelligence Engine.

Score = 0.40 × Travel_Time + 0.20 × Traffic + 0.15 × Accident_Risk
      + 0.15 × Weather_Risk + 0.10 × Road_Condition

All factors normalized to [0, 1] before combining.
Lower score = better route candidate.
Uses historical segment data. No fabricated road network.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


WEIGHTS = {
    "travel_time":     0.40,
    "traffic":         0.20,
    "accident_risk":   0.15,
    "weather_risk":    0.15,
    "road_condition":  0.10,
}

OUTPUT_DIR = Path(__file__).resolve().parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def _minmax_normalize(series):
    import numpy as np
    import pandas as pd
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - lo) / (hi - lo)


def load_segment_profiles():
    """Load per-segment historical aggregates."""
    import pandas as pd
    try:
        from ml.db_loader import load_segment_stats
        df = load_segment_stats()
        if not df.empty:
            return df
    except Exception as e:
        print(f"[RouteEngine] DB load failed, using fallback: {e}")

    # Fallback: try cached CSV
    cache = OUTPUT_DIR / "clustering_segments.csv"
    if cache.exists():
        return pd.read_csv(cache)

    raise RuntimeError("No segment data available. Run ETL pipeline first.")


def build_segment_scores(weather_code: Optional[int] = None,
                         hour: Optional[int] = None):
    """
    Computes multi-factor route intelligence scores for all S001-S500 segments.
    Returns a DataFrame sorted ascending by total_score (best first).
    """
    import numpy as np
    import pandas as pd
    df = load_segment_profiles()

    # Ensure numeric
    for col in ["mean_speed","mean_wait","mean_congestion","mean_incidents",
                "mean_density","mean_occupancy","mean_visibility","mean_rain"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # ── Factor 1: Travel Time proxy (inverse speed → higher wait = worse) ──
    # Normalize: higher wait_time and lower speed → higher score (worse)
    df["f_travel_time"] = 1.0
    if "mean_wait" in df.columns and df["mean_wait"].std() > 0:
        df["f_travel_time"] = _minmax_normalize(df["mean_wait"])
    elif "mean_speed" in df.columns and df["mean_speed"].std() > 0:
        # Invert speed so slow = high travel time
        df["f_travel_time"] = 1.0 - _minmax_normalize(df["mean_speed"])

    # ── Factor 2: Traffic congestion ────────────────────────────────────────
    df["f_traffic"] = 0.0
    if "mean_congestion" in df.columns:
        df["f_traffic"] = _minmax_normalize(df["mean_congestion"])
    elif "mean_density" in df.columns:
        df["f_traffic"] = _minmax_normalize(df["mean_density"])

    # ── Factor 3: Accident Risk ─────────────────────────────────────────────
    df["f_accident_risk"] = 0.0
    if "mean_incidents" in df.columns:
        df["f_accident_risk"] = _minmax_normalize(df["mean_incidents"])
    if "gridlock_count" in df.columns:
        gridlock_norm = _minmax_normalize(df["gridlock_count"])
        df["f_accident_risk"] = (df["f_accident_risk"] + gridlock_norm) / 2

    # ── Factor 4: Weather Risk ──────────────────────────────────────────────
    df["f_weather_risk"] = 0.0
    if "mean_rain" in df.columns:
        df["f_weather_risk"] = _minmax_normalize(df["mean_rain"])
    if "mean_visibility" in df.columns:
        # Low visibility = higher risk
        df["f_weather_risk"] = (df["f_weather_risk"] + (1 - _minmax_normalize(df["mean_visibility"]))) / 2

    # Apply weather code override if provided
    if weather_code is not None:
        # WMO weather code severity mapping
        weather_severity = {
            0: 0.0, 1: 0.0, 2: 0.1, 3: 0.2,
            45: 0.5, 48: 0.6,
            51: 0.3, 53: 0.4, 55: 0.5,
            61: 0.4, 63: 0.5, 65: 0.8,
            80: 0.4, 81: 0.6, 82: 0.9,
            95: 1.0
        }
        base_severity = weather_severity.get(weather_code, 0.3)
        df["f_weather_risk"] = df["f_weather_risk"].clip(lower=base_severity)

    # ── Factor 5: Road Condition ────────────────────────────────────────────
    df["f_road_condition"] = 0.0
    if "mean_occupancy" in df.columns:
        df["f_road_condition"] = _minmax_normalize(df["mean_occupancy"])

    # ── Peak hour adjustment ────────────────────────────────────────────────
    if hour is not None and 8 <= hour <= 11 or hour is not None and 17 <= hour <= 20:
        # During peak hours, increase traffic and travel time weight
        df["f_traffic"] = (df["f_traffic"] * 1.3).clip(upper=1.0)
        df["f_travel_time"] = (df["f_travel_time"] * 1.2).clip(upper=1.0)

    # ── Compute weighted total score ────────────────────────────────────────
    df["total_score"] = (
        WEIGHTS["travel_time"]   * df["f_travel_time"] +
        WEIGHTS["traffic"]       * df["f_traffic"] +
        WEIGHTS["accident_risk"] * df["f_accident_risk"] +
        WEIGHTS["weather_risk"]  * df["f_weather_risk"] +
        WEIGHTS["road_condition"]* df["f_road_condition"]
    )

    return df.sort_values("total_score").reset_index(drop=True)


def get_top_segments(n: int = 10,
                     weather_code: Optional[int] = None,
                     hour: Optional[int] = None,
                     exclude_segments: Optional[List[str]] = None) -> pd.DataFrame:
    """Returns top-n best (lowest score) road segments."""
    df = build_segment_scores(weather_code=weather_code, hour=hour)
    if exclude_segments:
        df = df[~df["road_segment_id"].isin(exclude_segments)]
    return df.head(n)


def explain_score(row: pd.Series) -> str:
    """Human-readable explanation of a segment's route score."""
    lines = [
        f"Route Score Breakdown for {row.get('road_segment_id', '?')}:",
        f"  Total Score: {row['total_score']:.4f} (lower=better)",
        f"",
        f"  {'Factor':<20} {'Weight':>6} {'Raw':>8} {'Contribution':>12}",
        f"  {'-'*50}",
    ]
    factor_map = [
        ("Travel Time",   "f_travel_time",   WEIGHTS["travel_time"]),
        ("Traffic",       "f_traffic",       WEIGHTS["traffic"]),
        ("Accident Risk", "f_accident_risk", WEIGHTS["accident_risk"]),
        ("Weather Risk",  "f_weather_risk",  WEIGHTS["weather_risk"]),
        ("Road Condition","f_road_condition", WEIGHTS["road_condition"]),
    ]
    for name, col, weight in factor_map:
        val = float(row.get(col, 0))
        contrib = weight * val
        lines.append(f"  {name:<20} {weight:>6.2f} {val:>8.4f} {contrib:>12.4f}")
    lines.append(f"")

    # Interpretation
    score = float(row["total_score"])
    if score < 0.25:
        interp = "✅ EXCELLENT — Minimal delays, safe conditions"
    elif score < 0.45:
        interp = "🟡 GOOD — Some congestion, manageable conditions"
    elif score < 0.65:
        interp = "🟠 MODERATE — Significant congestion or risk factors"
    else:
        interp = "🔴 POOR — High congestion, risky conditions"
    lines.append(f"  Assessment: {interp}")
    return "\n".join(lines)


def run_route_analysis(top_n: int = 10,
                       weather_code: Optional[int] = None,
                       hour: Optional[int] = None) -> Dict:
    """Run full route analysis and save results."""
    import pandas as pd
    print("\n" + "="*65)
    print("ROUTE INTELLIGENCE ENGINE — Historical Segment Comparison")
    print("="*65)
    if weather_code:
        print(f"Weather Code: {weather_code}")
    if hour is not None:
        print(f"Hour: {hour:02d}:00 {'(PEAK)' if 8<=hour<=11 or 17<=hour<=20 else '(Off-peak)'}")

    df = build_segment_scores(weather_code=weather_code, hour=hour)

    print(f"\nTop {top_n} Best Route Segments:")
    print(f"  {'Segment':<10} {'Score':>8} {'Speed':>8} {'Wait':>8} {'Congestion':>12} {'Label'}")
    print("  " + "-"*65)
    top = df.head(top_n)
    for _, row in top.iterrows():
        seg   = row.get("road_segment_id", "?")
        score = float(row["total_score"])
        speed = row.get("mean_speed", 0)
        wait  = row.get("mean_wait",  0)
        cong  = row.get("mean_congestion", 0)
        lbl   = row.get("cluster_label", "")
        print(f"  {seg:<10} {score:>8.4f} {float(speed):>8.1f} {float(wait):>8.1f} {float(cong):>12.4f}  {lbl}")

    print(f"\nWorst 5 Segments (avoid):")
    print("  " + "-"*65)
    for _, row in df.tail(5).iterrows():
        seg   = row.get("road_segment_id", "?")
        score = float(row["total_score"])
        print(f"  {seg:<10} {score:>8.4f}")

    print(f"\n{explain_score(df.iloc[0])}")

    # Segment score distribution
    score_buckets = pd.cut(df["total_score"],
                           bins=[0, 0.25, 0.45, 0.65, 1.01],
                           labels=["Excellent", "Good", "Moderate", "Poor"])
    dist = score_buckets.value_counts().to_dict()
    print(f"\nScore Distribution: {dist}")

    results = {
        "weather_code": weather_code,
        "hour": hour,
        "weights": WEIGHTS,
        "top_segments": top[
            ["road_segment_id","total_score","f_travel_time","f_traffic",
             "f_accident_risk","f_weather_risk","f_road_condition"]
        ].round(4).to_dict(orient="records"),
        "score_distribution": {str(k): int(v) for k,v in dist.items()},
        "best_segment": str(df.iloc[0].get("road_segment_id", "?")),
        "worst_segment": str(df.iloc[-1].get("road_segment_id", "?")),
    }

    out_path = OUTPUT_DIR / "route_analysis.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=float)
    df.to_csv(OUTPUT_DIR / "route_all_segments.csv", index=False)
    print(f"\n✓ Route analysis saved: {out_path}")
    return results


if __name__ == "__main__":
    import sys
    wc = int(sys.argv[1]) if len(sys.argv) > 1 else None
    hr = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    run_route_analysis(top_n=10, weather_code=wc, hour=hr)
