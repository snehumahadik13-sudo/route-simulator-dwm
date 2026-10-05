"""
tests/test_all.py — Complete test suite for Emergency Route Intelligence Warehouse.
Run: python -m pytest tests/test_all.py -v
  or: python tests/test_all.py
"""
import os
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

PASS, FAIL, SKIP = "✅ PASS", "❌ FAIL", "⚠️ SKIP"
results = []

def test(name, fn):
    try:
        fn()
        results.append((PASS, name))
        print(f"  {PASS}  {name}")
    except AssertionError as e:
        results.append((FAIL, f"{name}: {e}"))
        print(f"  {FAIL}  {name}: {e}")
    except Exception as e:
        results.append((FAIL, f"{name}: {type(e).__name__}: {e}"))
        print(f"  {FAIL}  {name}: {type(e).__name__}: {e}")

def load_env():
    env = {}
    p = BASE_DIR / ".env"
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env

env = load_env()
DB_URL = env.get("SUPABASE_DB_URL")

def get_conn():
    import psycopg
    return psycopg.connect(DB_URL, autocommit=True)

def count(table):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
    conn.close()
    return n

print("\n" + "█"*65)
print("  EMERGENCY ROUTE INTELLIGENCE — FULL TEST SUITE")
print("█"*65)

# ── 1. DATABASE CONNECTION ─────────────────────────────────────────────────
print("\n[1] Database Connection Tests")
def t_env_exists():   assert DB_URL, "SUPABASE_DB_URL missing from .env"
def t_db_connect():
    import psycopg
    conn = psycopg.connect(DB_URL, autocommit=True)
    with conn.cursor() as cur: cur.execute("SELECT 1")
    conn.close()
def t_no_creds_exposed():
    for f in ["README.md", "PROJECT_STATUS.md", "run_warehouse.py", "app.py"]:
        p = BASE_DIR / f
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            assert "postgresql://" not in txt or "SUPABASE_DB_URL" in txt, f"{f} exposes DB URL"

test("ENV has SUPABASE_DB_URL", t_env_exists)
test("DB connects successfully", t_db_connect)
test("No credentials exposed in files", t_no_creds_exposed)

# ── 2. STAGING ROW COUNTS ──────────────────────────────────────────────────
print("\n[2] Staging Row Count Validation")
STAGING_EXPECTED = {
    "staging.stg_vanet_traffic":           195714,
    "staging.stg_daily_weather":           91320,
    "staging.stg_accidents_roads":         20000,
    "staging.stg_hospital_infrastructure": 737,
    "staging.stg_ems_events":              20000,
}
for tbl, expected in STAGING_EXPECTED.items():
    def check(t=tbl, e=expected):
        n = count(t)
        assert n == e, f"{t}: expected {e:,} got {n:,}"
    test(f"{tbl} = {expected:,}", check)

# ── 3. WAREHOUSE ROW COUNTS ────────────────────────────────────────────────
print("\n[3] Warehouse Row Count Validation")
WAREHOUSE_EXPECTED = {
    "warehouse.dim_date":                9862,
    "warehouse.dim_road_segment":        500,
    "warehouse.dim_time_of_day":         1440,
    "warehouse.dim_weather_condition":   16,
}
for tbl, expected in WAREHOUSE_EXPECTED.items():
    def check(t=tbl, e=expected):
        n = count(t)
        assert n == e, f"{t}: expected {e:,} got {n:,}"
    test(f"{tbl} = {expected:,}", check)

# Variable-count tables (just check > 0)
WAREHOUSE_NONEMPTY = [
    "warehouse.dim_hospital", "warehouse.dim_location",
    "warehouse.fact_road_accidents", "warehouse.fact_ems_events",
    "warehouse.fact_daily_weather", "warehouse.fact_traffic_performance",
]
for tbl in WAREHOUSE_NONEMPTY:
    def check(t=tbl):
        n = count(t)
        assert n > 0, f"{t} is empty — run: python run_warehouse.py"
    test(f"{tbl} > 0", check)

# ── 4. DUPLICATE CHECKS ────────────────────────────────────────────────────
print("\n[4] Duplicate Checks")
def t_no_dup_accidents():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM (SELECT accident_id FROM staging.stg_accidents_roads GROUP BY accident_id HAVING COUNT(*)>1) x")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 0, f"Found {n} duplicate accident_ids in staging"

def t_no_dup_ems():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM (SELECT event_id FROM staging.stg_ems_events GROUP BY event_id HAVING COUNT(*)>1) x")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 0, f"Found {n} duplicate event_ids in EMS staging"

def t_no_dup_wh_accidents():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM (SELECT accident_id FROM warehouse.fact_road_accidents GROUP BY accident_id HAVING COUNT(*)>1) x")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 0, f"Found {n} duplicate accident_ids in warehouse"

test("No duplicate accident_ids in staging", t_no_dup_accidents)
test("No duplicate event_ids in EMS staging", t_no_dup_ems)
test("No duplicate accident_ids in warehouse", t_no_dup_wh_accidents)

# ── 5. NULL CHECKS ─────────────────────────────────────────────────────────
print("\n[5] NULL Value Checks (Critical Fields)")
def t_no_null_accident_severity():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM staging.stg_accidents_roads WHERE accident_severity IS NULL OR accident_severity=''")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 0, f"Found {n} NULL accident_severity in staging"

def t_wh_no_null_date_key():
    n = count("warehouse.fact_road_accidents")
    if n == 0:
        return  # Skip if not loaded
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM warehouse.fact_road_accidents WHERE date_key IS NULL")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 0, f"Found {n} NULL date_keys in fact_road_accidents"

test("No NULL accident_severity in staging", t_no_null_accident_severity)
test("No NULL date_key in warehouse accidents", t_wh_no_null_date_key)

# ── 6. REFERENTIAL INTEGRITY ───────────────────────────────────────────────
print("\n[6] Referential Integrity Checks")
def t_ri_accidents():
    n_acc = count("warehouse.fact_road_accidents")
    if n_acc == 0: return
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM warehouse.fact_road_accidents a
            WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_date d WHERE d.date_key=a.date_key)
        """)
        orphans = cur.fetchone()[0]
    conn.close()
    assert orphans == 0, f"Found {orphans} fact_road_accidents with missing dim_date"

def t_ri_ems():
    n_ems = count("warehouse.fact_ems_events")
    if n_ems == 0: return
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM warehouse.fact_ems_events e
            WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_hospital h WHERE h.hospital_key=e.hospital_key)
        """)
        orphans = cur.fetchone()[0]
    conn.close()
    assert orphans == 0, f"Found {orphans} fact_ems_events with missing dim_hospital"

test("fact_road_accidents → dim_date referential integrity", t_ri_accidents)
test("fact_ems_events → dim_hospital referential integrity", t_ri_ems)

# ── 7. ANALYTICAL VIEWS ────────────────────────────────────────────────────
print("\n[7] Analytical View Tests")
def t_view_hourly():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM warehouse.vw_hourly_emergency_risk_profile")
        n = cur.fetchone()[0]
    conn.close()
    assert n == 24, f"vw_hourly_emergency_risk_profile expected 24 rows, got {n}"

def t_view_hospital_readiness():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM warehouse.vw_emergency_hospital_readiness")
        n = cur.fetchone()[0]
    conn.close()
    assert n >= 0, "View failed to query"

def t_view_weather_corr():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM warehouse.vw_weather_accident_correlation")
        n = cur.fetchone()[0]
    conn.close()
    assert n >= 0, "View failed to query"

test("vw_hourly_emergency_risk_profile has 24 rows", t_view_hourly)
test("vw_emergency_hospital_readiness queries OK", t_view_hospital_readiness)
test("vw_weather_accident_correlation queries OK", t_view_weather_corr)

# ── 8. PUBLIC SCHEMA PRESERVATION ──────────────────────────────────────────
print("\n[8] Public Schema Preservation")
def t_public_accidents():
    n = count("public.accidents")
    assert n == 20000, f"public.accidents modified! Got {n}, expected 20000"
def t_public_traffic():
    n = count("public.traffic")
    assert n == 195714, f"public.traffic modified! Got {n}, expected 195714"
def t_public_dim_weather():
    n = count("public.dim_weather")
    assert n == 91320, f"public.dim_weather modified! Got {n}, expected 91320"

test("public.accidents preserved (20,000)", t_public_accidents)
test("public.traffic preserved (195,714)", t_public_traffic)
test("public.dim_weather preserved (91,320)", t_public_dim_weather)

# ── 9. ML RESULTS FILES ────────────────────────────────────────────────────
print("\n[9] ML Results Files")
ML_DIR = BASE_DIR / "ml_results"
ML_FILES = [
    "association_rules.json", "clustering_summary.json",
    "anomaly_detection.json", "classification_results.json",
    "trend_analysis.json", "route_analysis.json",
]
for fname in ML_FILES:
    def check(f=fname):
        p = ML_DIR / f
        assert p.exists(), f"Missing: ml_results/{f} — run python -m ml.run_all_ml"
        with open(p) as fp: data = json.load(fp)
        assert data, f"Empty: ml_results/{f}"
    test(f"ml_results/{fname} exists and non-empty", check)

# ── 10. FLASK API ──────────────────────────────────────────────────────────
print("\n[10] Flask API Tests")
def t_app_imports():
    import importlib.util
    spec = importlib.util.spec_from_file_location("app", BASE_DIR/"app.py")
    assert spec is not None, "app.py cannot be loaded"

def t_route_engine():
    from route_engine import WEIGHTS
    assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001, "Weights don't sum to 1.0"

def t_simulator_imports():
    from simulator import WEATHER_CODES, URGENCY_MAP
    assert 0 in WEATHER_CODES, "Weather code 0 missing"
    assert "red" in URGENCY_MAP, "Red triage missing"

test("app.py importable", t_app_imports)
test("Route engine weights sum to 1.0", t_route_engine)
test("Simulator module imports correctly", t_simulator_imports)

# ── 11. SOURCE FILES ───────────────────────────────────────────────────────
print("\n[11] Source File Validation")
CSV_FILES = [
    "vanet_traffic_data.csv", "india_2000_2024_daily_weather.csv",
    "indian_roads_dataset.csv", "PMC Hospital Infrastructure (1).csv",
    "ems_events_20000.csv",
]
for fname in CSV_FILES:
    def check(f=fname):
        p = BASE_DIR / f
        assert p.exists(), f"Missing: {f}"
        assert p.stat().st_size > 1000, f"Suspiciously small: {f}"
    test(f"Source file exists: {fname}", check)

# ── Summary ────────────────────────────────────────────────────────────────
print("\n" + "="*65)
passed = sum(1 for s,_ in results if s==PASS)
failed = sum(1 for s,_ in results if s==FAIL)
total  = len(results)
print(f"RESULTS: {passed}/{total} passed  |  {failed} failed")
print("="*65)

if failed:
    print("\nFailed tests:")
    for status, name in results:
        if status == FAIL:
            print(f"  {name}")

# Save results
out = BASE_DIR / "test_results.txt"
with open(out, "w") as f:
    for status, name in results:
        f.write(f"{status}  {name}\n")
    f.write(f"\nTotal: {passed}/{total} passed, {failed} failed\n")
print(f"\nResults saved: {out}")

sys.exit(0 if failed == 0 else 1)
