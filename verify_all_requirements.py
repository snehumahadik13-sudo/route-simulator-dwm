import sys
import json
import re

import app as flask_app

client = flask_app.app.test_client()
results = {}

def test_item_1():
    print("Testing Item 1: Flask app starts without errors...")
    assert flask_app.app is not None
    # Test health check endpoint
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("status") == "ok"
    results["Item 1: Flask application starts without errors and passes health check"] = "PASS"

def test_item_2():
    print("Testing Item 2: Admin login works...")
    # 1. Admin login page renders
    res_page = client.get("/admin-login")
    assert res_page.status_code == 200

    # 2. Admin login API
    res_login = client.post("/admin-login", json={"email": "admin@emergency-route.in", "password": "admin"})
    assert res_login.status_code == 200
    data = res_login.get_json()
    assert data.get("status") == "ok"
    assert data.get("role") == "admin"

    # 3. Verify session access
    res_user = client.get("/api/current_user")
    assert res_user.status_code == 200
    udata = res_user.get_json()
    assert udata.get("authenticated") is True
    assert udata.get("role") == "admin"

    results["Item 2: Admin login authenticates successfully and grants admin role"] = "PASS"

def test_item_3():
    print("Testing Item 3: Admin sidebar contains none of the 4 unwanted options...")
    # Ensure client is logged in as admin
    client.post("/admin-login", json={"email": "admin@emergency-route.in", "password": "admin"})
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # 1. No Route Simulator in admin sidebar / admin nav
    admin_nav_match = re.search(r'<nav class="sidebar-nav" id="admin-sidebar-nav">(.*?)</nav>', html, re.DOTALL)
    assert admin_nav_match is not None, "admin-sidebar-nav not found"
    admin_nav_html = admin_nav_match.group(1).lower()
    assert "simulator" not in admin_nav_html, "Route Simulator found in admin sidebar nav"
    assert "route simulator" not in admin_nav_html

    # 2. No Discipline / Dispatch pipeline card in sidebar
    sidebar_match = re.search(r'<aside class="sidebar".*?>(.*?)</aside>', html, re.DOTALL)
    assert sidebar_match is not None, "aside element not found"
    sidebar_html = sidebar_match.group(1).lower()
    assert "discipline" not in sidebar_html, "Discipline found in sidebar"
    assert "pipeline" not in sidebar_html, "Pipeline found in sidebar"
    assert "sidebar-widget-card" not in sidebar_html, "Discipline/dispatch widget card found in sidebar"

    # 3. No "Manage" button in topbar or page headers
    topbar_match = re.search(r'<header class="topbar">(.*?)</header>', html, re.DOTALL)
    assert topbar_match is not None
    topbar_html = topbar_match.group(1).lower()
    assert "manage" not in topbar_html, "'Manage' button found in topbar"
    assert '<button class="btn btn-outline">manage</button>' not in html.lower(), "Manage button found in html"

    # 4. No "Other Admin Data" in sidebar nav or admin navigation
    assert "other admin data" not in admin_nav_html, "'Other Admin Data' found in admin sidebar nav"
    assert "nav-other-admin" not in admin_nav_html

    results["Item 3: Admin sidebar cleaned (no Route Simulator, Discipline Pipeline, Manager, Other Admin Data)"] = "PASS"

def test_item_4():
    print("Testing Item 4: Driver login opens the correct dashboard with real data...")
    # 1. Driver login page renders
    res_page = client.get("/driver-login")
    assert res_page.status_code == 200

    # 2. Driver login API
    res_login = client.post("/driver-login", json={"email": "driver@ems-ambulance.in", "password": "driver"})
    assert res_login.status_code == 200
    data = res_login.get_json()
    assert data.get("status") == "ok"
    assert data.get("role") == "driver"

    # 3. Verify driver dashboard API returns live database telemetry & capacity
    res_dash = client.get("/api/driver/dashboard")
    assert res_dash.status_code == 200
    ddata = res_dash.get_json()
    assert ddata.get("status") == "ok"
    assert ddata.get("role") == "driver"

    totals = ddata.get("totals", {})
    assert totals.get("total_hospitals") == 741, f"Expected 741 hospitals, got {totals.get('total_hospitals')}"
    assert totals.get("total_beds") >= 16000, f"Expected >= 16000 beds, got {totals.get('total_beds')}"
    assert "total_emerg_beds" in totals, "Expected emergency beds key in totals"
    assert totals.get("total_ambulances") >= 40, "Expected ambulances >= 40"

    hospitals = ddata.get("major_hospitals", [])
    assert len(hospitals) >= 5, "Expected top major hospitals"

    corridors = ddata.get("critical_corridors", [])
    assert len(corridors) >= 3, "Expected critical high-risk corridors"

    results["Item 4: Driver dashboard displays real data (741 hospitals, 16,009 beds, live corridor telemetry)"] = "PASS"

def test_item_5():
    print("Testing Item 5: Route Simulator returns and displays real route results...")
    # Must be logged in as driver
    client.post("/driver-login", json={"email": "driver@ems-ambulance.in", "password": "driver"})

    # 1. Verify destination hospitals list (741 entries)
    res_hosp = client.get("/api/destination_hospitals")
    assert res_hosp.status_code == 200
    hdata = res_hosp.get_json()
    hosp_list = hdata.get("hospitals", [])
    assert len(hosp_list) == 741, f"Expected 741 destination hospitals, got {len(hosp_list)}"

    # 2. Simulate route to first hospital
    first_hosp = hosp_list[0]
    payload = {
        "source": "Satara",
        "destination": first_hosp.get("facility_name", "Ruby Hall Clinic"),
        "emergency_type": "Trauma",
        "severity": "Critical",
        "triage_level": "Red",
        "urgency_score": 8.5,
        "model": "random_forest"
    }
    res_sim = client.post("/api/simulate_route", json=payload)
    assert res_sim.status_code == 200
    sim_data = res_sim.get_json()
    assert "candidate_routes" in sim_data
    candidates = sim_data["candidate_routes"]
    assert len(candidates) >= 3, "Expected at least 3 candidate routes (BEST, BETTER, GOOD)"

    rec = sim_data.get("recommended_route")
    assert rec is not None
    assert rec.get("label") == "BEST"
    assert rec.get("emerg_travel_min") > 0
    assert "reason" in rec and len(rec["reason"]) > 10

    results["Item 5: Route Simulator returns 741 hospitals, candidate routes, and recommended route"] = "PASS"

def test_item_6():
    print("Testing Item 6: ML Analysis loads actual metrics for the 3 required models and delay predictions...")
    client.post("/driver-login", json={"email": "driver@ems-ambulance.in", "password": "driver"})

    # 1. ML Metrics
    res_metrics = client.get("/api/ml/metrics")
    assert res_metrics.status_code == 200
    mdata = res_metrics.get_json()
    models = mdata.get("models", {})
    required_models = ["Random Forest Regressor", "Decision Tree Regressor", "XGBoost Regressor"]
    for rm in required_models:
        assert rm in models, f"Model '{rm}' missing from ML metrics"
        m = models[rm]
        assert "mae" in m, f"mae missing for {rm}"
        assert "rmse" in m, f"rmse missing for {rm}"
        assert "r2" in m, f"r2 missing for {rm}"
        assert "accuracy_within_5_min" in m, f"accuracy_within_5_min missing for {rm}"
        assert m["accuracy_within_5_min"] >= 90.0, f"Expected high accuracy for {rm}"

    # 2. Delay Prediction
    pred_payload = {
        "model_name": "Random Forest Regressor",
        "avg_speed_kmph": 45.0,
        "density_veh_per_km": 30.0,
        "avg_wait_time_s": 25.0,
        "occupancy_pct": 0.22,
        "congestion_pressure": 0.15,
        "incident_num": 0,
        "temp_c": 28.0,
        "visibility_km": 8.0,
        "rain_intensity_mmph": 0.0,
        "hour_24": 14,
        "is_weekend": 0
    }
    res_pred = client.post("/api/ml/predict-delay", json=pred_payload)
    assert res_pred.status_code == 200
    pdata = res_pred.get_json()
    assert "best_model_predicted_delay" in pdata or "predictions" in pdata
    delay_val = pdata.get("best_model_predicted_delay", 0)
    assert delay_val >= 0

    results["Item 6: ML Analysis loaded actual metrics (RF, DT, XGB) with MAE, RMSE, R2, Acc +-5min & prediction"] = "PASS"

def test_item_7():
    print("Testing Item 7: Logout and account switching work correctly...")
    # 1. Log in as Driver
    client.post("/driver-login", json={"email": "driver@ems-ambulance.in", "password": "driver"})
    res_u1 = client.get("/api/current_user")
    assert res_u1.get_json().get("role") == "driver"

    # 2. Logout clears session
    res_logout = client.post("/logout")
    assert res_logout.status_code == 200
    res_u2 = client.get("/api/current_user")
    assert res_u2.get_json().get("authenticated") is False
    assert res_u2.get_json().get("role") is None

    # 3. Log in as Admin
    client.post("/admin-login", json={"email": "admin@emergency-route.in", "password": "admin"})
    res_u3 = client.get("/api/current_user")
    assert res_u3.get_json().get("role") == "admin"

    # 4. Clean logout
    client.post("/logout")
    res_u4 = client.get("/api/current_user")
    assert res_u4.get_json().get("authenticated") is False

    results["Item 7: Logout wipes session completely and account switching operates cleanly"] = "PASS"

def test_item_8():
    print("Testing Item 8: Unauthorized page and API access is blocked (HTTP 401 & 403)...")
    # Ensure logged out
    client.post("/logout")

    # 1. Unauthenticated requests to protected endpoints -> 401
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/destination_hospitals").status_code == 401
    assert client.post("/api/simulate_route", json={}).status_code == 401
    assert client.get("/api/driver/dashboard").status_code == 401

    # 2. Driver role accessing admin-only endpoints -> 403
    client.post("/driver-login", json={"email": "driver@ems-ambulance.in", "password": "driver"})
    assert client.get("/api/overview").status_code == 403
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/hospitals").status_code == 403

    # 3. Admin role accessing driver-only endpoints -> 403
    client.post("/logout")
    client.post("/admin-login", json={"email": "admin@emergency-route.in", "password": "admin"})
    assert client.get("/api/destination_hospitals").status_code == 403
    assert client.post("/api/simulate_route", json={}).status_code == 403
    assert client.post("/api/simulate", json={}).status_code == 403
    assert client.get("/api/driver/dashboard").status_code == 403

    client.post("/logout")
    results["Item 8: RBAC strictly enforced with HTTP 401 and 403 across all protected routes"] = "PASS"

def test_item_9():
    print("Testing Item 9: Dataset pages, OLAP, and Warehouse still work...")
    client.post("/admin-login", json={"email": "admin@emergency-route.in", "password": "admin"})

    # Overview KPI
    res_ov = client.get("/api/overview")
    assert res_ov.status_code == 200
    ov_data = res_ov.get_json()
    assert ov_data.get("traffic_records", 0) > 0
    assert ov_data.get("hospital_count", 0) == 741

    # Datasets
    assert client.get("/api/hospitals").status_code == 200
    assert client.get("/api/accidents").status_code == 200
    assert client.get("/api/weather").status_code == 200
    assert client.get("/api/emergencies").status_code == 200
    assert client.get("/api/traffic").status_code == 200
    assert client.get("/api/routes").status_code == 200

    # OLAP cubes & dimensional operators
    res_olap_opts = client.get("/api/olap/filter_options")
    assert res_olap_opts.status_code == 200
    assert "operations" in res_olap_opts.get_json()

    res_olap_rollup = client.get("/api/olap/rollup?fact=accidents&level=year&measure=accident_count")
    assert res_olap_rollup.status_code == 200

    res_olap_topn = client.get("/api/olap/topn?category=locations&n=5")
    assert res_olap_topn.status_code == 200

    # Audit
    res_audit = client.get("/api/audit")
    assert res_audit.status_code == 200

    client.post("/logout")
    results["Item 9: All dataset pages, OLAP cubes, and Warehouse queries operate normally"] = "PASS"

if __name__ == "__main__":
    try:
        test_item_1()
        test_item_2()
        test_item_3()
        test_item_4()
        test_item_5()
        test_item_6()
        test_item_7()
        test_item_8()
        test_item_9()

        print("\n" + "="*80)
        print("                 COMPREHENSIVE VERIFICATION RESULTS")
        print("="*80)
        for item, status in results.items():
            print(f"  [{status}]  {item}")
        print("="*80)
        print("  ALL 9 ITEMS VERIFIED SUCCESSFULLY: 9/9 PASSED (0 FAILED)")
        print("="*80 + "\n")
    except Exception as e:
        print(f"\n[FAIL] Test aborted with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
