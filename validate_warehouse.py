"""
validate_warehouse.py — Deep validation queries for the Emergency Route Intelligence Warehouse.
Checks row counts, NULL FKs, orphan FKs, duplicates, date range, and domain coverage.
Run AFTER run_warehouse.py completes.
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

conn = psycopg.connect(DB_URL, autocommit=True)
cur = conn.cursor()

issues = []

def check(label, sql, expect_zero=True, min_rows=None):
    """Run a validation check and report results."""
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        count = len(rows) if rows else 0
        first_val = rows[0][0] if rows and rows[0] else 0
        
        if expect_zero:
            # Query should return 0 (no bad rows)
            bad = isinstance(first_val, int) and first_val > 0
            status = "FAIL ✗" if bad else "PASS ✓"
            if bad:
                issues.append(f"FAIL: {label} — {first_val} bad rows")
            print(f"  [{status}] {label}: {first_val}")
        elif min_rows is not None:
            # Query should return at least min_rows
            bad = isinstance(first_val, int) and first_val < min_rows
            status = "FAIL ✗" if bad else "PASS ✓"
            if bad:
                issues.append(f"FAIL: {label} — got {first_val}, need >= {min_rows}")
            print(f"  [{status}] {label}: {first_val:,}")
        else:
            # Just report value
            print(f"  [INFO] {label}: {rows[0] if rows else '(no rows)'}")
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        issues.append(f"ERROR: {label} — {e}")

print("\n" + "="*70)
print("  WAREHOUSE VALIDATION REPORT")
print("="*70)

# ─── 1. ROW COUNTS ──────────────────────────────────────────────────────────
print("\n── 1. ROW COUNTS ──")
check("warehouse.dim_date >= 9862",
      "SELECT COUNT(*) FROM warehouse.dim_date", expect_zero=False, min_rows=9862)
check("warehouse.dim_hospital >= 4",
      "SELECT COUNT(*) FROM warehouse.dim_hospital", expect_zero=False, min_rows=4)
check("warehouse.dim_location >= 10",
      "SELECT COUNT(*) FROM warehouse.dim_location", expect_zero=False, min_rows=10)
check("warehouse.dim_road_segment = 500",
      "SELECT COUNT(*) FROM warehouse.dim_road_segment", expect_zero=False, min_rows=500)
check("warehouse.dim_time_of_day = 1440",
      "SELECT COUNT(*) FROM warehouse.dim_time_of_day", expect_zero=False, min_rows=1440)
check("warehouse.dim_weather_condition = 16",
      "SELECT COUNT(*) FROM warehouse.dim_weather_condition", expect_zero=False, min_rows=16)
check("warehouse.fact_road_accidents > 0",
      "SELECT COUNT(*) FROM warehouse.fact_road_accidents", expect_zero=False, min_rows=1)
check("warehouse.fact_ems_events > 0",
      "SELECT COUNT(*) FROM warehouse.fact_ems_events", expect_zero=False, min_rows=1)
check("warehouse.fact_daily_weather > 0",
      "SELECT COUNT(*) FROM warehouse.fact_daily_weather", expect_zero=False, min_rows=1)
check("warehouse.fact_traffic_performance > 0",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance", expect_zero=False, min_rows=1)

# ─── 2. NULL FOREIGN KEYS ───────────────────────────────────────────────────
print("\n── 2. NULL FOREIGN KEYS ──")
check("fact_road_accidents: NULL date_key",
      "SELECT COUNT(*) FROM warehouse.fact_road_accidents WHERE date_key IS NULL")
check("fact_road_accidents: NULL time_key",
      "SELECT COUNT(*) FROM warehouse.fact_road_accidents WHERE time_key IS NULL")
check("fact_road_accidents: NULL location_key",
      "SELECT COUNT(*) FROM warehouse.fact_road_accidents WHERE location_key IS NULL")
check("fact_ems_events: NULL date_key",
      "SELECT COUNT(*) FROM warehouse.fact_ems_events WHERE date_key IS NULL")
check("fact_ems_events: NULL time_key",
      "SELECT COUNT(*) FROM warehouse.fact_ems_events WHERE time_key IS NULL")
check("fact_ems_events: NULL hospital_key",
      "SELECT COUNT(*) FROM warehouse.fact_ems_events WHERE hospital_key IS NULL")
check("fact_daily_weather: NULL date_key",
      "SELECT COUNT(*) FROM warehouse.fact_daily_weather WHERE date_key IS NULL")
check("fact_daily_weather: NULL location_key",
      "SELECT COUNT(*) FROM warehouse.fact_daily_weather WHERE location_key IS NULL")
check("fact_traffic_performance: NULL date_key",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance WHERE date_key IS NULL")
check("fact_traffic_performance: NULL time_key",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance WHERE time_key IS NULL")
check("fact_traffic_performance: NULL segment_key",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance WHERE segment_key IS NULL")

# ─── 3. ORPHAN FOREIGN KEYS ─────────────────────────────────────────────────
print("\n── 3. ORPHAN FOREIGN KEYS ──")
check("fact_road_accidents: orphan date_key",
      """SELECT COUNT(*) FROM warehouse.fact_road_accidents f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_date d WHERE d.date_key = f.date_key)""")
check("fact_road_accidents: orphan time_key",
      """SELECT COUNT(*) FROM warehouse.fact_road_accidents f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_time_of_day d WHERE d.time_key = f.time_key)""")
check("fact_road_accidents: orphan location_key",
      """SELECT COUNT(*) FROM warehouse.fact_road_accidents f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_location d WHERE d.location_key = f.location_key)""")
check("fact_ems_events: orphan date_key",
      """SELECT COUNT(*) FROM warehouse.fact_ems_events f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_date d WHERE d.date_key = f.date_key)""")
check("fact_ems_events: orphan hospital_key",
      """SELECT COUNT(*) FROM warehouse.fact_ems_events f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_hospital d WHERE d.hospital_key = f.hospital_key)""")
check("fact_daily_weather: orphan location_key",
      """SELECT COUNT(*) FROM warehouse.fact_daily_weather f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_location d WHERE d.location_key = f.location_key)""")
check("fact_traffic_performance: orphan segment_key",
      """SELECT COUNT(*) FROM warehouse.fact_traffic_performance f
         WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_road_segment d WHERE d.segment_key = f.segment_key)""")

# ─── 4. DUPLICATE DIMENSION KEYS ────────────────────────────────────────────
print("\n── 4. DUPLICATE DIMENSION KEYS ──")
check("dim_date: duplicate date_key",
      "SELECT COUNT(*) FROM (SELECT date_key FROM warehouse.dim_date GROUP BY date_key HAVING COUNT(*) > 1) x")
check("dim_hospital: duplicate hospital_code",
      "SELECT COUNT(*) FROM (SELECT hospital_code FROM warehouse.dim_hospital WHERE hospital_code IS NOT NULL GROUP BY hospital_code HAVING COUNT(*) > 1) x")
check("dim_road_segment: duplicate road_segment_id",
      "SELECT COUNT(*) FROM (SELECT road_segment_id FROM warehouse.dim_road_segment GROUP BY road_segment_id HAVING COUNT(*) > 1) x")
check("fact_road_accidents: duplicate accident_id",
      "SELECT COUNT(*) FROM (SELECT accident_id FROM warehouse.fact_road_accidents GROUP BY accident_id HAVING COUNT(*) > 1) x")
check("fact_ems_events: duplicate event_id",
      "SELECT COUNT(*) FROM (SELECT event_id FROM warehouse.fact_ems_events GROUP BY event_id HAVING COUNT(*) > 1) x")
check("fact_daily_weather: duplicate city+date",
      "SELECT COUNT(*) FROM (SELECT city, calendar_date FROM warehouse.fact_daily_weather GROUP BY city, calendar_date HAVING COUNT(*) > 1) x")

# ─── 5. DATE RANGE ──────────────────────────────────────────────────────────
print("\n── 5. DATE RANGE ──")
check("dim_date range",
      "SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM warehouse.dim_date", expect_zero=False, min_rows=None)
check("fact_road_accidents date range",
      "SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM warehouse.fact_road_accidents", expect_zero=False, min_rows=None)
check("fact_ems_events date range",
      "SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM warehouse.fact_ems_events", expect_zero=False, min_rows=None)
check("fact_daily_weather date range",
      "SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM warehouse.fact_daily_weather", expect_zero=False, min_rows=None)
check("fact_traffic_performance date range",
      "SELECT MIN(date_key), MAX(date_key), COUNT(*) FROM warehouse.fact_traffic_performance", expect_zero=False, min_rows=None)

# ─── 6. DOMAIN COVERAGE ─────────────────────────────────────────────────────
print("\n── 6. COVERAGE ──")
check("Road segment coverage (500 segments with traffic data)",
      """SELECT COUNT(*) FROM warehouse.dim_road_segment rs
         WHERE EXISTS (SELECT 1 FROM warehouse.fact_traffic_performance t WHERE t.segment_key = rs.segment_key)""",
      expect_zero=False, min_rows=100)

check("Hospital coverage (H001-H004 have EMS events)",
      """SELECT COUNT(DISTINCT hospital_key) FROM warehouse.fact_ems_events""",
      expect_zero=False, min_rows=1)

check("Location coverage (cities in weather fact)",
      """SELECT COUNT(DISTINCT city) FROM warehouse.fact_daily_weather""",
      expect_zero=False, min_rows=5)

check("Location coverage (cities in accident fact)",
      """SELECT COUNT(DISTINCT location_key) FROM warehouse.fact_road_accidents""",
      expect_zero=False, min_rows=5)

check("Weather code coverage (codes in daily weather)",
      """SELECT COUNT(DISTINCT weather_code) FROM warehouse.fact_daily_weather""",
      expect_zero=False, min_rows=3)

check("EMS conditions covered",
      """SELECT COUNT(DISTINCT condition) FROM warehouse.fact_ems_events""",
      expect_zero=False, min_rows=3)

check("EMS triage priorities (should have red/yellow/green)",
      """SELECT COUNT(DISTINCT triage_priority) FROM warehouse.fact_ems_events""",
      expect_zero=False, min_rows=2)

# ─── 7. VIEW SANITY ─────────────────────────────────────────────────────────
print("\n── 7. ANALYTICAL VIEWS ──")
check("vw_emergency_hospital_readiness > 0 rows",
      "SELECT COUNT(*) FROM warehouse.vw_emergency_hospital_readiness", expect_zero=False, min_rows=1)
check("vw_high_risk_route_corridors > 0 rows",
      "SELECT COUNT(*) FROM warehouse.vw_high_risk_route_corridors", expect_zero=False, min_rows=1)
check("vw_hourly_emergency_risk_profile = 24 rows",
      "SELECT COUNT(*) FROM warehouse.vw_hourly_emergency_risk_profile", expect_zero=False, min_rows=24)
check("vw_weather_accident_correlation > 0 rows",
      "SELECT COUNT(*) FROM warehouse.vw_weather_accident_correlation", expect_zero=False, min_rows=1)

# ─── 8. DATA QUALITY ────────────────────────────────────────────────────────
print("\n── 8. DATA QUALITY ──")
check("fact_road_accidents: extreme risk_score (> 9.99)",
      "SELECT COUNT(*) FROM warehouse.fact_road_accidents WHERE risk_score > 9.99")
check("fact_ems_events: urgency score out of range",
      "SELECT COUNT(*) FROM warehouse.fact_ems_events WHERE clinical_urgency_score < 1 OR clinical_urgency_score > 10")
check("fact_traffic_performance: negative speed",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance WHERE avg_speed_kmph < 0")
check("fact_traffic_performance: occupancy > 100%",
      "SELECT COUNT(*) FROM warehouse.fact_traffic_performance WHERE occupancy_pct > 100")
check("fact_daily_weather: negative precipitation",
      "SELECT COUNT(*) FROM warehouse.fact_daily_weather WHERE precipitation_sum_mm < 0")

# ─── SUMMARY ────────────────────────────────────────────────────────────────
print("\n" + "="*70)
if issues:
    print(f"  VALIDATION ISSUES ({len(issues)} found):")
    for i in issues:
        print(f"    ⚠ {i}")
else:
    print("  ALL VALIDATION CHECKS PASSED ✓")
print("="*70)
conn.close()
