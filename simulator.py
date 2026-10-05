"""
simulator.py
Emergency Route Simulator — Decision-Support Tool.
CLI and API interface for route scoring, hospital readiness, risk factors.
"""
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


WEATHER_CODES = {
    0: "Clear Sky",    1: "Mainly Clear",   2: "Partly Cloudy",
    3: "Overcast",    45: "Fog",            48: "Rime Fog",
    51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
    61: "Slight Rain",   63: "Moderate Rain",    65: "Heavy Rain",
    80: "Rain Showers",  81: "Moderate Showers", 82: "Violent Showers",
    95: "Thunderstorm",
}

URGENCY_MAP = {
    "red":    {"label": "🔴 CRITICAL",  "multiplier": 1.3},
    "yellow": {"label": "🟡 URGENT",    "multiplier": 1.1},
    "green":  {"label": "🟢 STABLE",    "multiplier": 1.0},
}


def run_simulation(
    city: str = "Pune",
    hour: int = 10,
    weather_code: int = 0,
    triage_priority: str = "red",
    hospital_preference: Optional[str] = None,
    top_segments: int = 5,
) -> Dict[str, Any]:
    """
    Run a full emergency dispatch simulation.
    Returns structured decision-support data.
    """
    print("\n" + "█"*65)
    print("  EMERGENCY ROUTE INTELLIGENCE — DISPATCH SIMULATOR")
    print("█"*65)
    print(f"\n  City:            {city}")
    print(f"  Dispatch Hour:   {hour:02d}:00  {'(PEAK HOUR)' if 8<=hour<=11 or 17<=hour<=20 else '(Off-peak)'}")
    print(f"  Weather:         {WEATHER_CODES.get(weather_code, 'Unknown')} (code={weather_code})")
    print(f"  Triage Priority: {URGENCY_MAP.get(triage_priority.lower(), {}).get('label', triage_priority.upper())}")
    if hospital_preference:
        print(f"  Hospital Pref:   {hospital_preference}")

    result: Dict[str, Any] = {
        "inputs": {
            "city": city,
            "hour": hour,
            "weather_code": weather_code,
            "weather_description": WEATHER_CODES.get(weather_code, "Unknown"),
            "triage_priority": triage_priority,
            "hospital_preference": hospital_preference,
        },
        "route_candidates": [],
        "hospital_recommendations": [],
        "risk_summary": {},
        "recommendation": "",
    }

    # ── Route Scoring ──────────────────────────────────────────────────────
    print("\n📍 Computing Route Scores...")
    try:
        from route_engine import build_segment_scores, explain_score
        df_scores = build_segment_scores(weather_code=weather_code, hour=hour)

        urgency_mult = URGENCY_MAP.get(triage_priority.lower(), {}).get("multiplier", 1.0)
        # For critical cases, penalize high-risk routes more
        df_scores["adjusted_score"] = (df_scores["total_score"] * urgency_mult).clip(upper=1.0)
        df_scores = df_scores.sort_values("adjusted_score").reset_index(drop=True)

        top_routes = df_scores.head(top_segments)
        print(f"\n  Top {top_segments} Route Candidates:")
        print(f"  {'Seg':<8} {'Score':>8} {'Adj':>8} {'Speed':>7} {'Wait':>7} {'Risk':>8}")
        print("  " + "-"*55)
        route_candidates = []
        for rank, (_, row) in enumerate(top_routes.iterrows(), 1):
            seg   = row.get("road_segment_id", "?")
            score = float(row["total_score"])
            adj   = float(row["adjusted_score"])
            speed = float(row.get("mean_speed", 0))
            wait  = float(row.get("mean_wait",  0))
            acc_r = float(row.get("f_accident_risk", 0))
            print(f"  {seg:<8} {score:>8.4f} {adj:>8.4f} {speed:>7.1f} {wait:>7.1f} {acc_r:>8.4f}")

            candidate = {
                "rank": rank,
                "segment_id": seg,
                "total_score": round(score, 4),
                "adjusted_score": round(adj, 4),
                "mean_speed_kmph": round(speed, 1),
                "mean_wait_s": round(wait, 1),
                "factors": {
                    "travel_time": round(float(row.get("f_travel_time", 0)), 4),
                    "traffic": round(float(row.get("f_traffic", 0)), 4),
                    "accident_risk": round(float(row.get("f_accident_risk", 0)), 4),
                    "weather_risk": round(float(row.get("f_weather_risk", 0)), 4),
                    "road_condition": round(float(row.get("f_road_condition", 0)), 4),
                },
                "cluster_label": str(row.get("cluster_label", "Unknown")),
            }
            route_candidates.append(candidate)

        result["route_candidates"] = route_candidates
        if route_candidates:
            best = route_candidates[0]
            result["recommendation"] = (
                f"RECOMMENDED ROUTE: Segment {best['segment_id']} "
                f"(Score={best['total_score']:.4f}, Speed={best['mean_speed_kmph']:.1f}km/h)"
            )
            print(f"\n  ✅ BEST ROUTE: {best['segment_id']} — Score {best['total_score']:.4f}")
            print(f"  {explain_score(df_scores.iloc[0])}")

    except Exception as e:
        print(f"  Route scoring failed: {e}")
        result["route_error"] = str(e)

    # ── Hospital Recommendations ───────────────────────────────────────────
    print("\n🏥 Hospital Readiness...")
    try:
        from ml.db_loader import query_df
        hospitals_query = """
            SELECT h.hospital_code, h.facility_name, h.facility_type,
                   h.total_beds, h.emergency_beds, h.ambulance_count,
                   COUNT(e.ems_fact_key) as dispatches_today
            FROM warehouse.dim_hospital h
            LEFT JOIN warehouse.fact_ems_events e ON h.hospital_key = e.hospital_key
            WHERE h.hospital_code IN ('H001','H002','H003','H004')
            GROUP BY h.hospital_code, h.facility_name, h.facility_type,
                     h.total_beds, h.emergency_beds, h.ambulance_count
            ORDER BY dispatches_today ASC
        """
        df_hosp = query_df(hospitals_query)
        if not df_hosp.empty:
            print(f"  {'Code':<6} {'Type':<22} {'Total Dispatches':>16}")
            for _, row in df_hosp.iterrows():
                preferred = " ← PREFERRED" if hospital_preference and row["hospital_code"] == hospital_preference else ""
                print(f"  {row['hospital_code']:<6} {str(row['facility_type']):<22} {int(row['dispatches_today']):>16,}{preferred}")

            result["hospital_recommendations"] = df_hosp.to_dict(orient="records")
    except Exception as e:
        print(f"  Hospital readiness: {e}")
        result["hospital_error"] = str(e)

    # ── Risk Summary ───────────────────────────────────────────────────────
    weather_risk_level = "HIGH" if weather_code in (65,80,81,82,95,45,48) else \
                         "MODERATE" if weather_code in (51,53,55,61,63,3) else "LOW"

    peak_risk = "PEAK HOUR" if 8<=hour<=11 or 17<=hour<=20 else "OFF-PEAK"

    result["risk_summary"] = {
        "weather_risk": weather_risk_level,
        "time_risk": peak_risk,
        "triage_severity": triage_priority.upper(),
        "dispatch_urgency": URGENCY_MAP.get(triage_priority.lower(), {}).get("label", "?"),
    }

    print(f"\n⚠️  Risk Summary:")
    for k, v in result["risk_summary"].items():
        print(f"  {k:<25} {v}")
    print(f"\n  DECISION: {result.get('recommendation','No route data available')}")

    return result


def interactive_cli():
    """Interactive command-line simulation mode."""
    print("\n" + "="*65)
    print("  EMERGENCY ROUTE SIMULATOR — Interactive Mode")
    print("="*65)
    print("  (Press Enter for defaults)")

    city = input("  City [Pune]: ").strip() or "Pune"
    try:
        hour = int(input("  Hour (0-23) [10]: ").strip() or "10")
    except ValueError:
        hour = 10

    print(f"\n  Weather Codes: 0=Clear 45=Fog 61=Rain 65=HeavyRain 95=Thunder")
    try:
        wc = int(input("  Weather code [0]: ").strip() or "0")
    except ValueError:
        wc = 0

    priority = input("  Triage priority (red/yellow/green) [red]: ").strip().lower() or "red"
    hosp = input("  Hospital preference (H001/H002/H003/H004) []: ").strip() or None

    result = run_simulation(
        city=city, hour=hour, weather_code=wc,
        triage_priority=priority, hospital_preference=hosp
    )
    out = Path("ml_results") / "simulation_result.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Result saved: {out}")
    return result


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        interactive_cli()
    else:
        # Demo simulation
        result = run_simulation(
            city="Pune", hour=9, weather_code=63,
            triage_priority="red", hospital_preference="H003"
        )
        out = Path("ml_results") / "simulation_result.json"
        out.parent.mkdir(exist_ok=True)
        with open(out, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nDemo simulation saved: {out}")
