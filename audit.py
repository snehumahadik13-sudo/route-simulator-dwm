"""
audit.py — Read-Only Exact Row Counts for ALL schemas/tables.
Run: python audit.py
"""
import os, sys
from pathlib import Path

def load_env(path=r"C:\Users\harsh\Downloads\data\.env"):
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

env = load_env()
DB_URL = env.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
if not DB_URL:
    sys.exit("ERROR: SUPABASE_DB_URL not in .env")

try:
    import psycopg
except ImportError:
    sys.exit("Run: pip install 'psycopg[binary]'")

TABLES = {
    "PUBLIC": [
        "public.accidents","public.dim_hospital","public.dim_location",
        "public.dim_road","public.dim_time","public.dim_weather",
        "public.fact_emergency_response","public.hospitals",
        "public.roads","public.traffic","public.weather",
    ],
    "STAGING": [
        "staging.stg_accidents_roads","staging.stg_daily_weather",
        "staging.stg_ems_events","staging.stg_hospital_infrastructure",
        "staging.stg_vanet_traffic",
    ],
    "WAREHOUSE": [
        "warehouse.dim_date","warehouse.dim_hospital","warehouse.dim_location",
        "warehouse.dim_road_segment","warehouse.dim_time_of_day",
        "warehouse.dim_weather_condition","warehouse.fact_daily_weather",
        "warehouse.fact_ems_events","warehouse.fact_road_accidents",
        "warehouse.fact_traffic_performance",
    ],
    "VIEWS": [
        "warehouse.vw_emergency_hospital_readiness",
        "warehouse.vw_high_risk_route_corridors",
        "warehouse.vw_hourly_emergency_risk_profile",
        "warehouse.vw_weather_accident_correlation",
    ],
}

print("\n" + "="*65)
print("  FULL DATABASE ROW COUNT AUDIT — READ ONLY")
print("="*65)

conn = psycopg.connect(DB_URL, autocommit=True)
results = {}

with conn.cursor() as cur:
    for section, tables in TABLES.items():
        print(f"\n{'─'*65}")
        print(f"{section}:")
        print(f"{'─'*65}")
        for qt in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {qt}")
                n = cur.fetchone()[0]
            except Exception as e:
                conn.rollback()
                n = f"ERR: {e}"
            results[qt] = n
            ns = f"{n:,}" if isinstance(n, int) else str(n)
            empty = "  ← EMPTY" if isinstance(n,int) and n==0 else ""
            print(f"  {qt:<50} {ns:>10}{empty}")

conn.close()

print("\n" + "="*65)
print("AUDIT COMPLETE")
print("="*65)

# Write results file
out = Path(r"C:\Users\harsh\Downloads\data\audit_results.txt")
with out.open("w") as f:
    for k, v in results.items():
        f.write(f"{k}={v}\n")
print(f"Results saved to: {out}")
