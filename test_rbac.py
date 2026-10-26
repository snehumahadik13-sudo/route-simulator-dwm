import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import app as flask_app

client = flask_app.app.test_client()

PASS = "PASS"
FAIL = "FAIL"
results = []

def run_test(name, fn):
    try:
        ok, msg = fn()
        status = PASS if ok else FAIL
        results.append((status, name, msg))
        print(f"  [{status}]  {name:<55} {msg}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  [{FAIL}]  {name:<55} ERROR: {e}")

print("\n" + "="*75)
print("  Emergency Route Intelligence — RBAC & Authentication Test Suite")
print("="*75 + "\n")

# 1. Unauthenticated checks
def test_unauthenticated_state():
    r = client.get('/api/current_user')
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get('authenticated') is False
    return ok, f"status={r.status_code} authenticated={d.get('authenticated')}"
run_test("GET /api/current_user (unauthenticated)", test_unauthenticated_state)

def test_unauthenticated_admin_api():
    r = client.get('/api/overview')
    ok = r.status_code == 401
    return ok, f"status={r.status_code} (expected 401)"
run_test("GET /api/overview (unauthenticated -> 401)", test_unauthenticated_admin_api)

def test_unauthenticated_driver_api():
    r = client.get('/api/destination_hospitals')
    ok = r.status_code == 401
    return ok, f"status={r.status_code} (expected 401)"
run_test("GET /api/destination_hospitals (unauthenticated -> 401)", test_unauthenticated_driver_api)

# 2. Admin Login
def test_admin_login():
    r = client.post('/admin-login', json={"email": "admin@emergency-route.in", "password": "admin"})
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("role") == "admin"
    return ok, f"status={r.status_code} role={d.get('role')}"
run_test("POST /admin-login", test_admin_login)

def test_admin_current_user():
    r = client.get('/api/current_user')
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("authenticated") is True and d.get("role") == "admin"
    return ok, f"status={r.status_code} role={d.get('role')}"
run_test("GET /api/current_user (as Admin)", test_admin_current_user)

def test_admin_access_overview():
    r = client.get('/api/overview')
    ok = r.status_code == 200
    d = json.loads(r.data)
    return ok, f"status={r.status_code} traffic_records={d.get('traffic_records')}"
run_test("GET /api/overview (as Admin -> 200)", test_admin_access_overview)

def test_admin_access_audit():
    r = client.get('/api/audit')
    ok = r.status_code == 200
    d = json.loads(r.data)
    wh = d.get('warehouse', {})
    return ok, f"status={r.status_code} warehouse_tables={len(wh)}"
run_test("GET /api/audit (as Admin -> 200)", test_admin_access_audit)

def test_admin_blocked_from_driver_api():
    r = client.get('/api/destination_hospitals')
    ok = r.status_code == 403
    return ok, f"status={r.status_code} (expected 403 Forbidden)"
run_test("GET /api/destination_hospitals (Admin forbidden -> 403)", test_admin_blocked_from_driver_api)

def test_admin_blocked_from_simulator():
    r = client.post('/api/simulate', json={})
    ok = r.status_code == 403
    return ok, f"status={r.status_code} (expected 403 Forbidden)"
run_test("POST /api/simulate (Admin forbidden -> 403)", test_admin_blocked_from_simulator)

# 3. Logout
def test_logout():
    r = client.post('/logout')
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("status") == "ok"
    return ok, f"status={r.status_code} msg={d.get('message')}"
run_test("POST /logout", test_logout)

def test_after_logout_state():
    r = client.get('/api/current_user')
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("authenticated") is False
    return ok, f"status={r.status_code} authenticated={d.get('authenticated')}"
run_test("GET /api/current_user (after logout -> not auth)", test_after_logout_state)

def test_after_logout_overview():
    r = client.get('/api/overview')
    ok = r.status_code == 401
    return ok, f"status={r.status_code} (expected 401 Unauthorized)"
run_test("GET /api/overview (after logout -> 401)", test_after_logout_overview)

# 4. Driver Login
def test_driver_login():
    r = client.post('/driver-login', json={"email": "driver@ems-ambulance.in", "password": "driver"})
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("role") == "driver"
    return ok, f"status={r.status_code} role={d.get('role')}"
run_test("POST /driver-login", test_driver_login)

def test_driver_current_user():
    r = client.get('/api/current_user')
    d = json.loads(r.data)
    ok = r.status_code == 200 and d.get("authenticated") is True and d.get("role") == "driver"
    return ok, f"status={r.status_code} role={d.get('role')}"
run_test("GET /api/current_user (as Driver)", test_driver_current_user)

def test_driver_blocked_from_admin_overview():
    r = client.get('/api/overview')
    ok = r.status_code == 403
    return ok, f"status={r.status_code} (expected 403 Forbidden)"
run_test("GET /api/overview (Driver forbidden -> 403)", test_driver_blocked_from_admin_overview)

def test_driver_blocked_from_admin_audit():
    r = client.get('/api/audit')
    ok = r.status_code == 403
    return ok, f"status={r.status_code} (expected 403 Forbidden)"
run_test("GET /api/audit (Driver forbidden -> 403)", test_driver_blocked_from_admin_audit)

def test_driver_access_destination_hospitals():
    r = client.get('/api/destination_hospitals')
    ok = r.status_code == 200
    d = json.loads(r.data)
    return ok, f"status={r.status_code} hospitals_count={len(d.get('hospitals', []))}"
run_test("GET /api/destination_hospitals (as Driver -> 200)", test_driver_access_destination_hospitals)

def test_driver_access_ml_metrics():
    r = client.get('/api/ml/metrics')
    ok = r.status_code == 200
    d = json.loads(r.data)
    return ok, f"status={r.status_code} best_model={d.get('best_model')}"
run_test("GET /api/ml/metrics (as Driver -> 200)", test_driver_access_ml_metrics)

print("\n" + "="*75)
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
print(f"  RESULTS: {passed}/{len(results)} passed  |  {failed} failed")
print("="*75 + "\n")
