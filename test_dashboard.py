"""
test_dashboard.py — Self-contained API test for the Emergency Route Intelligence Dashboard
Run BEFORE starting app.py to validate all backend endpoints are correct.
Usage:  python test_dashboard.py
"""
import json, sys, decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# ── Patch exec so we can import app without starting the server ──────────────
import app as flask_app

# Override Decimal serialization for json.dumps
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super().default(o)

client = flask_app.app.test_client()

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results = []

def test(name, fn):
    try:
        ok, msg = fn()
        status = PASS if ok else FAIL
        results.append((status, name, msg))
        print(f"  {status}  {name:<50} {msg}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL}  {name:<50} ERROR: {e}")

print("\n" + "="*70)
print("  Emergency Route Intelligence Dashboard — API Test Suite")
print("="*70 + "\n")

# ── Health ────────────────────────────────────────────────────────────────────
def test_health():
    r = client.get('/api/health')
    d = json.loads(r.data)
    ok = d.get('status') == 'ok' and d.get('warehouse_connected')
    return ok, f"traffic_rows={d.get('traffic_rows', '?')}"
test("GET /api/health", test_health)

# ── Overview ──────────────────────────────────────────────────────────────────
def test_overview():
    r = client.get('/api/overview')
    d = json.loads(r.data)
    traffic = d.get('traffic_records', 0)
    accidents = d.get('accident_count', 0)
    ems = d.get('ems_event_count', 0)
    ok = traffic > 0 and accidents > 0 and ems > 0
    return ok, f"traffic={traffic:,} accidents={accidents:,} ems={ems:,}"
test("GET /api/overview (KPI counts)", test_overview)

def test_overview_warehouse():
    r = client.get('/api/overview')
    d = json.loads(r.data)
    wh = d.get('warehouse', {})
    facts_ok = all(wh.get(k, 0) > 0 for k in ['fact_road_accidents','fact_ems_events','fact_daily_weather','fact_traffic_performance'])
    return facts_ok, f"facts loaded: accidents={wh.get('fact_road_accidents',0):,} traffic={wh.get('fact_traffic_performance',0):,}"
test("GET /api/overview (warehouse facts)", test_overview_warehouse)

# ── Traffic ───────────────────────────────────────────────────────────────────
def test_traffic():
    r = client.get('/api/traffic')
    d = json.loads(r.data)
    hourly = d.get('hourly', [])
    segs   = d.get('top_segments', [])
    labels = d.get('congestion_labels', [])
    ok = len(hourly) == 24 and len(segs) > 0 and len(labels) > 0
    return ok, f"hourly={len(hourly)} segments={len(segs)} congestion_labels={len(labels)}"
test("GET /api/traffic", test_traffic)

# ── Accidents ─────────────────────────────────────────────────────────────────
def test_accidents():
    r = client.get('/api/accidents')
    d = json.loads(r.data)
    sv  = d.get('severity', [])
    loc = d.get('by_location', [])
    hourly = d.get('hourly', [])
    ok = len(sv) > 0 and len(loc) > 0 and len(hourly) == 24
    return ok, f"severities={len(sv)} locations={len(loc)} hourly={len(hourly)}"
test("GET /api/accidents", test_accidents)

# ── Weather ───────────────────────────────────────────────────────────────────
def test_weather():
    r = client.get('/api/weather')
    d = json.loads(r.data)
    codes = d.get('by_code', [])
    cities = d.get('by_city', [])
    ok = len(codes) > 0 and len(cities) > 0
    return ok, f"weather_codes={len(codes)} cities={len(cities)}"
test("GET /api/weather", test_weather)

# ── Emergencies ───────────────────────────────────────────────────────────────
def test_emergencies():
    r = client.get('/api/emergencies')
    d = json.loads(r.data)
    triage = d.get('triage', [])
    hourly = d.get('hourly', [])
    hosps  = d.get('by_hospital', [])
    ok = len(triage) > 0 and len(hourly) == 24
    return ok, f"triage_cats={len(triage)} hourly={len(hourly)} ems_hospitals={len(hosps)}"
test("GET /api/emergencies", test_emergencies)

# ── Routes ────────────────────────────────────────────────────────────────────
def test_routes():
    r = client.get('/api/routes')
    d = json.loads(r.data)
    segs = d.get('segments', [])
    ok = len(segs) == 500
    if segs:
        first = segs[0]
        has_fields = all(k in first for k in ['road_segment_id','overall_risk_score','traffic_risk','speed_risk'])
        ok = ok and has_fields
    return ok, f"segments={len(segs)} top_risk={segs[0].get('overall_risk_score','?') if segs else '?'}"
test("GET /api/routes (500 segments, risk scores)", test_routes)

# ── Hospitals ─────────────────────────────────────────────────────────────────
def test_hospitals():
    r = client.get('/api/hospitals')
    d = json.loads(r.data)
    ems = d.get('ems_hospitals', [])
    pmc = d.get('pmc_summary', {})
    types = d.get('by_type', [])
    ok = len(ems) == 4 and pmc.get('total_facilities', 0) > 0
    return ok, f"ems={len(ems)} pmc_facilities={pmc.get('total_facilities','?')} pmc_beds={pmc.get('total_beds','?')}"
test("GET /api/hospitals", test_hospitals)

# ── Peak Hours (legacy) ───────────────────────────────────────────────────────
def test_peak_hours():
    r = client.get('/api/peak_hours')
    d = json.loads(r.data)
    ok = len(d) == 24 and not (len(d) and 'error' in d[0])
    return ok, f"rows={len(d)}"
test("GET /api/peak_hours", test_peak_hours)

# ── Severity (legacy) ─────────────────────────────────────────────────────────
def test_severity():
    r = client.get('/api/severity')
    d = json.loads(r.data)
    ok = len(d) > 0 and not (d and 'error' in d[0])
    return ok, f"severity_categories={len(d)}"
test("GET /api/severity", test_severity)

# ── Weather Impact (legacy) ───────────────────────────────────────────────────
def test_weather_impact():
    r = client.get('/api/weather_impact')
    d = json.loads(r.data)
    ok = len(d) > 0 and not (d and 'error' in d[0])
    return ok, f"rows={len(d)}"
test("GET /api/weather_impact", test_weather_impact)

# ── High-risk segments (legacy) ───────────────────────────────────────────────
def test_high_risk():
    r = client.get('/api/high_risk_segments')
    d = json.loads(r.data)
    ok = len(d) == 20 and not (d and 'error' in d[0])
    return ok, f"segments_returned={len(d)}"
test("GET /api/high_risk_segments", test_high_risk)

# ── Hospital readiness (legacy) ───────────────────────────────────────────────
def test_hospital_readiness():
    r = client.get('/api/hospital_readiness')
    d = json.loads(r.data)
    ok = len(d) > 0 and not (d and 'error' in d[0])
    has_dispatch = any(r.get('total_dispatches', 0) for r in d)
    return ok and has_dispatch, f"rows={len(d)} has_dispatch_data={has_dispatch}"
test("GET /api/hospital_readiness", test_hospital_readiness)

# ── Filter options ────────────────────────────────────────────────────────────
def test_filter_options():
    r = client.get('/api/filter_options')
    d = json.loads(r.data)
    ok = len(d.get('cities', [])) > 0 and len(d.get('severities', [])) > 0
    return ok, f"cities={len(d.get('cities',[]))} severities={len(d.get('severities',[]))}"
test("GET /api/filter_options", test_filter_options)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*70)
passed = sum(1 for s,_,_ in results if s == PASS)
failed = sum(1 for s,_,_ in results if s == FAIL)
total  = len(results)
print(f"  RESULTS: {passed}/{total} passed  |  {failed} failed")
print("="*70 + "\n")

if failed == 0:
    print("  🎉 ALL TESTS PASSED — Dashboard is ready!")
    print("  Run:  python app.py")
    print("  Open: http://localhost:5000\n")
else:
    print("  Some tests failed. Check the errors above.")
    print("  Ensure the warehouse is fully loaded before running the dashboard.\n")
