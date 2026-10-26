import requests

s = requests.Session()

# 1. Login
res = s.post("http://127.0.0.1:5000/api/login", json={
    "role": "driver",
    "email": "driver@ems-ambulance.in",
    "password": "driver"
})
print("1. /api/login:", res.status_code, res.text[:120])

# 2. Driver Dashboard
res_dash = s.get("http://127.0.0.1:5000/api/driver/dashboard")
print("2. /api/driver/dashboard:", res_dash.status_code, res_dash.text[:200])

# 3. Destination Hospitals
res_hosp = s.get("http://127.0.0.1:5000/api/destination_hospitals")
print("3. /api/destination_hospitals:", res_hosp.status_code, f"count={len(res_hosp.json().get('hospitals', [])) if res_hosp.ok else res_hosp.text}")

# 4. Simulate Route
res_sim = s.post("http://127.0.0.1:5000/api/simulate_route", json={
    "source": "Satara",
    "destination": "Ruby Hall Clinic (Sasoon Rd)",
    "emergency_type": "Trauma",
    "severity": "Critical",
    "model": "random_forest"
})
print("4. /api/simulate_route:", res_sim.status_code, res_sim.text[:200])

# 5. ML Metrics
res_ml = s.get("http://127.0.0.1:5000/api/ml/metrics")
print("5. /api/ml/metrics:", res_ml.status_code, res_ml.text[:200])

# 6. ML Predict Delay
res_pred = s.post("http://127.0.0.1:5000/api/ml/predict-delay", json={
    "avg_speed_kmph": 40.0,
    "density_veh_per_km": 30.0,
    "congestion_pressure": 0.4,
    "occupancy_pct": 0.4,
    "flow_veh_per_hr": 800.0,
    "queue_length_veh": 3.0,
    "rain_intensity_mmph": 0.0,
    "visibility_km": 8.0,
    "temp_c": 28.0,
    "hour_24": 14
})
print("6. /api/ml/predict-delay:", res_pred.status_code, res_pred.text[:200])
