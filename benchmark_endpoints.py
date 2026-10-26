import time
import app

client = app.app.test_client()
client.post('/driver-login', json={'email':'driver@ems-ambulance.in', 'password':'driver'})

endpoints = [
    ("GET /api/driver/dashboard", lambda: client.get("/api/driver/dashboard")),
    ("GET /api/destination_hospitals", lambda: client.get("/api/destination_hospitals")),
    ("POST /api/simulate_route", lambda: client.post("/api/simulate_route", json={
        "source": "Satara", "destination": "EMS Destination Facility (H001)",
        "emergency_type": "Trauma", "severity": "Critical", "model": "random_forest"
    })),
    ("GET /api/ml/metrics", lambda: client.get("/api/ml/metrics")),
    ("POST /api/ml/predict-delay", lambda: client.post("/api/ml/predict-delay", json={
        "avg_speed_kmph": 40.0, "density_veh_per_km": 30.0, "congestion_pressure": 0.4,
        "occupancy_pct": 0.4, "flow_veh_per_hr": 800.0, "queue_length_veh": 3.0,
        "rain_intensity_mmph": 0.0, "visibility_km": 8.0, "temp_c": 28.0, "hour_24": 14
    }))
]

for name, fn in endpoints:
    t0 = time.time()
    res = fn()
    dt = time.time() - t0
    print(f"{name:<35} -> status {res.status_code} in {dt:.2f}s")
