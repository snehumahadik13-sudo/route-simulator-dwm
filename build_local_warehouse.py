import os
import sqlite3
import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"c:\Users\harsh\Downloads\data")
DB_PATH = BASE_DIR / "warehouse.db"

if DB_PATH.exists():
    try:
        os.remove(DB_PATH)
    except Exception:
        pass

print(f"Building local SQLite warehouse at: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

for tbl in ["vw_weather_accident_correlation", "vw_high_risk_route_corridors", "vw_emergency_hospital_readiness", "vw_hourly_emergency_risk_profile", "fact_traffic_performance", "fact_daily_weather", "fact_ems_events", "fact_road_accidents", "dim_road_segment", "dim_location", "dim_hospital", "dim_time_of_day", "dim_date"]:
    try:
        cur.execute(f"DROP VIEW IF EXISTS {tbl}")
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    except Exception:
        pass

# 1. Dim Date (2000 - 2026)
print("1/7 Creating dim_date...")
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,
    calendar_date TEXT,
    year INTEGER,
    quarter INTEGER,
    month INTEGER,
    month_name TEXT,
    day INTEGER,
    day_of_week TEXT,
    day_of_week_num INTEGER,
    is_weekend INTEGER,
    festival TEXT,
    full_date TEXT,
    season TEXT
);
""")

import datetime
start_date = datetime.date(2000, 1, 1)
end_date = datetime.date(2026, 12, 31)
delta = datetime.timedelta(days=1)
curr = start_date
date_rows = []
while curr <= end_date:
    dk = curr.year * 10000 + curr.month * 100 + curr.day
    dow_num = curr.isoweekday()
    m = curr.month
    season = "Summer" if m in (3,4,5) else ("Monsoon" if m in (6,7,8,9) else ("Post-Monsoon" if m in (10,11) else "Winter"))
    date_rows.append((
        dk, str(curr), curr.year, (curr.month - 1) // 3 + 1, curr.month,
        curr.strftime("%B"), curr.day, curr.strftime("%A"), dow_num,
        1 if dow_num in (6, 7) else 0, None, str(curr), season
    ))
    curr += delta

cur.executemany("INSERT OR IGNORE INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", date_rows)
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_date_year ON dim_date(year);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_date_month ON dim_date(month);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_date_quarter ON dim_date(quarter);")

# 2. Dim Time Of Day
print("2/7 Creating dim_time_of_day...")
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_time_of_day (
    time_key INTEGER PRIMARY KEY,
    time_value TEXT,
    hour_24 INTEGER,
    minute INTEGER,
    time_of_day_bucket TEXT,
    is_peak_hour INTEGER
);
""")
time_rows = []
for h in range(24):
    for m in range(60):
        tk = h * 100 + m
        is_peak = 1 if ((8 <= h <= 11) or (17 <= h <= 20)) else 0
        if 0 <= h < 6: bucket = "Night"
        elif 6 <= h < 12: bucket = "Morning Peak" if (8 <= h <= 11) else "Early Morning"
        elif 12 <= h < 17: bucket = "Midday"
        elif 17 <= h < 21: bucket = "Evening Peak"
        else: bucket = "Late Evening"
        time_rows.append((tk, f"{h:02d}:{m:02d}:00", h, m, bucket, is_peak))

cur.executemany("INSERT OR IGNORE INTO dim_time_of_day VALUES (?,?,?,?,?,?)", time_rows)
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_time_hour ON dim_time_of_day(hour_24);")

# 3. Dim Hospital
print("3/7 Loading dim_hospital...")
cur.execute("DROP TABLE IF EXISTS dim_hospital;")
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_hospital (
    hospital_key INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_code TEXT UNIQUE,
    facility_name TEXT,
    facility_type TEXT,
    ownership_class TEXT,
    ward_name TEXT,
    zone_no INTEGER,
    total_beds INTEGER,
    emergency_beds INTEGER,
    doctor_count INTEGER,
    ambulance_count INTEGER,
    has_ambulance_service INTEGER,
    pharmacy_available INTEGER
);
""")

hosp_csv = BASE_DIR / "PMC Hospital Infrastructure (1).csv"
if hosp_csv.exists():
    df_hosp = pd.read_csv(hosp_csv, encoding="utf-8", encoding_errors="replace")
    ems_hospitals = [
        ("H001", "Sassoon General Hospital / EMS Cardiac Center (H001)", "EMS Cardiac Specialty Center", "Public", "Pune Station", 5, 1296, 60, 320, 8, 1, 1),
        ("H002", "K.E.M. Hospital / EMS Stroke Center (H002)", "EMS Stroke Specialty Center", "Private Trust", "Rasta Peth", 5, 550, 40, 140, 6, 1, 1),
        ("H003", "Ruby Hall Clinic / EMS Level 1 Trauma Center (H003)", "Level 1 Trauma Center", "Private", "Dhole Patil Road", 2, 750, 50, 180, 10, 1, 1),
        ("H004", "Bharati Hospital / EMS General Emergency (H004)", "General Emergency & Critical Care", "Private", "Dhankawadi", 3, 850, 45, 160, 7, 1, 1)
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO dim_hospital 
        (hospital_code, facility_name, facility_type, ownership_class, ward_name, zone_no, total_beds, emergency_beds, doctor_count, ambulance_count, has_ambulance_service, pharmacy_available)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, ems_hospitals)

    h_rows = []
    idx = 5
    for _, r in df_hosp.iterrows():
        fname = str(r.get("Facility Name", "")).strip()
        if not fname or fname == "nan": continue
        code = f"PMC-{idx-4:04d}"
        ftype = str(r.get("Type  (Hospital / Nursing Home / Lab)", "Hospital")).strip()
        oclass = str(r.get(" Class : (Public / Private)", "Private")).strip()
        ward = str(r.get("Ward Name", "")).strip()
        zno = pd.to_numeric(r.get("Zone No."), errors='coerce')
        zno = int(zno) if pd.notna(zno) else 1
        tbeds = pd.to_numeric(r.get("Number of Beds in facility type"), errors='coerce')
        tbeds = int(tbeds) if pd.notna(tbeds) else 0
        ebeds = pd.to_numeric(r.get("Number of Beds in Emergency Wards "), errors='coerce')
        ebeds = int(ebeds) if pd.notna(ebeds) else 0
        amb = pd.to_numeric(r.get("Count of Ambulance"), errors='coerce')
        amb = int(amb) if pd.notna(amb) else 0
        has_amb = 1 if str(r.get("Ambulance Service Available", "")).strip().lower() == "yes" else 0
        has_rx = 1 if str(r.get("Pharmacy Available : Yes/No", "")).strip().lower() == "yes" else 0
        h_rows.append((code, fname, ftype, oclass, ward, zno, tbeds, ebeds, 50, amb, has_amb, has_rx))
        idx += 1

    cur.executemany("""
        INSERT OR IGNORE INTO dim_hospital 
        (hospital_code, facility_name, facility_type, ownership_class, ward_name, zone_no, total_beds, emergency_beds, doctor_count, ambulance_count, has_ambulance_service, pharmacy_available)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, h_rows)

print(f"Loaded {cur.execute('SELECT COUNT(*) FROM dim_hospital').fetchone()[0]} hospitals.")

# 4. Dim Location & Dim Road Segment & Fact Road Accidents
print("4/7 Loading dim_location and fact_road_accidents...")
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_location (
    location_key INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT UNIQUE,
    state TEXT,
    country TEXT
);
""")

cur.execute("DROP TABLE IF EXISTS dim_road_segment;")
cur.execute("""
CREATE TABLE dim_road_segment (
    segment_key INTEGER PRIMARY KEY AUTOINCREMENT,
    road_segment_id TEXT UNIQUE,
    road_name TEXT,
    segment_identifier TEXT,
    corridor_group TEXT,
    length_km REAL,
    speed_limit_kmph REAL,
    lanes INTEGER
);
""")

# Load Indian Roads / Accidents Dataset
acc_csv = BASE_DIR / "indian_roads_dataset.csv"
if acc_csv.exists():
    df_acc = pd.read_csv(acc_csv, encoding="utf-8", encoding_errors="replace")
    
    cities = df_acc["city"].dropna().unique()
    cur.executemany("INSERT OR IGNORE INTO dim_location (city, state, country) VALUES (?, 'Maharashtra', 'India')", [(c,) for c in cities])
    loc_map = dict(cur.execute("SELECT city, location_key FROM dim_location").fetchall())

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_road_accidents (
        accident_fact_key INTEGER PRIMARY KEY AUTOINCREMENT,
        accident_id INTEGER,
        date_key INTEGER,
        time_key INTEGER,
        location_key INTEGER,
        road_type TEXT,
        lanes INTEGER,
        traffic_signal INTEGER,
        weather TEXT,
        visibility TEXT,
        temperature_c REAL,
        traffic_density TEXT,
        cause TEXT,
        accident_severity TEXT,
        vehicles_involved INTEGER,
        casualties INTEGER,
        is_peak_hour INTEGER,
        risk_score REAL,
        is_fatal INTEGER
    );
    """)

    acc_rows = []
    for idx_row, r in df_acc.iterrows():
        dt_str = str(r.get("date", "2024-01-01"))
        try:
            dt = pd.to_datetime(dt_str)
            dk = dt.year * 10000 + dt.month * 100 + dt.day
        except Exception:
            dk = 20240101

        tm_str = str(r.get("time", "12:00"))
        try:
            parts = tm_str.split(":")
            tk = int(parts[0]) * 100 + int(parts[1]) if len(parts) >= 2 else 1200
        except Exception:
            tk = 1200

        loc_k = loc_map.get(r.get("city"), 1)
        sev = str(r.get("accident_severity", "simple injury")).strip().lower()
        is_fatal = 1 if "fatal" in sev else 0
        casualties = int(r.get("casualties", 1)) if pd.notna(r.get("casualties")) else 1
        risk = float(r.get("risk_score", 0.5)) if pd.notna(r.get("risk_score")) else 0.5

        acc_rows.append((
            int(r.get("accident_id", idx_row)),
            dk, tk, loc_k,
            str(r.get("road_type", "highway")).strip(),
            int(r.get("lanes", 2)) if pd.notna(r.get("lanes")) else 2,
            1 if str(r.get("traffic_signal", "")).strip().lower() in ("true", "1", "yes") else 0,
            str(r.get("weather", "clear")).strip(),
            str(r.get("visibility", "good")).strip(),
            float(r.get("temperature", 28.0)) if pd.notna(r.get("temperature")) else 28.0,
            str(r.get("traffic_density", "medium")).strip(),
            str(r.get("cause", "speeding")).strip(),
            sev,
            int(r.get("vehicles_involved", 2)) if pd.notna(r.get("vehicles_involved")) else 2,
            casualties,
            1 if ((800 <= tk <= 1159) or (1700 <= tk <= 2059)) else 0,
            risk,
            is_fatal
        ))

    cur.executemany("""
        INSERT INTO fact_road_accidents (
            accident_id, date_key, time_key, location_key, road_type, lanes, traffic_signal,
            weather, visibility, temperature_c, traffic_density, cause, accident_severity,
            vehicles_involved, casualties, is_peak_hour, risk_score, is_fatal
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, acc_rows)
    print(f"Loaded {len(acc_rows):,} road accidents.")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_dk ON fact_road_accidents(date_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_tk ON fact_road_accidents(time_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_lk ON fact_road_accidents(location_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_sev ON fact_road_accidents(accident_severity);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_wx ON fact_road_accidents(weather);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acc_rt ON fact_road_accidents(road_type);")

# 5. Load EMS Events
print("5/7 Loading fact_ems_events...")
ems_csv = BASE_DIR / "ems_events_20000.csv"
if ems_csv.exists():
    df_ems = pd.read_csv(ems_csv, encoding="utf-8", encoding_errors="replace")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_ems_events (
        ems_fact_key INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        date_key INTEGER,
        time_key INTEGER,
        hospital_key INTEGER,
        condition TEXT,
        chief_complaint TEXT,
        patient_age INTEGER,
        patient_gender TEXT,
        sbp INTEGER,
        heart_rate INTEGER,
        spo2 INTEGER,
        gcs INTEGER,
        triage_priority TEXT,
        hospital_type_requested TEXT,
        clinical_urgency_score REAL,
        city TEXT
    );
    """)

    hosp_map = dict(cur.execute("SELECT hospital_code, hospital_key FROM dim_hospital").fetchall())

    ems_rows = []
    for idx_row, r in df_ems.iterrows():
        ts_str = str(r.get("timestamp", "2024-01-01T12:00:00"))
        try:
            dt = pd.to_datetime(ts_str)
            dk = dt.year * 10000 + dt.month * 100 + dt.day
            tk = dt.hour * 100 + dt.minute
        except Exception:
            dk, tk = 20240101, 1200

        h_code = str(r.get("hospital_id", "H001")).strip()
        h_k = hosp_map.get(h_code, 1)

        ems_rows.append((
            str(r.get("event_id", f"EMS-{idx_row}")),
            dk, tk, h_k,
            str(r.get("condition", "trauma")).strip(),
            str(r.get("chief_complaint", "injury")).strip(),
            int(r.get("age", 40)) if pd.notna(r.get("age")) else 40,
            str(r.get("gender", "male")).strip(),
            int(r.get("sbp", 120)) if pd.notna(r.get("sbp")) else 120,
            int(r.get("heart_rate", 80)) if pd.notna(r.get("heart_rate")) else 80,
            int(r.get("spo2", 98)) if pd.notna(r.get("spo2")) else 98,
            int(r.get("gcs", 15)) if pd.notna(r.get("gcs")) else 15,
            str(r.get("triage_priority", "RED")).strip().upper(),
            str(r.get("hospital_type", "level_1_trauma")).strip(),
            float(r.get("clinical_urgency_score", 8.0)) if pd.notna(r.get("clinical_urgency_score")) else 8.0,
            "Pune"
        ))

    cur.executemany("""
        INSERT INTO fact_ems_events (
            event_id, date_key, time_key, hospital_key, condition, chief_complaint,
            patient_age, patient_gender, sbp, heart_rate, spo2, gcs, triage_priority,
            hospital_type_requested, clinical_urgency_score, city
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ems_rows)
    print(f"Loaded {len(ems_rows):,} EMS events.")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ems_dk ON fact_ems_events(date_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ems_tk ON fact_ems_events(time_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ems_triage ON fact_ems_events(triage_priority);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ems_city ON fact_ems_events(city);")

# 6. Load VANET Traffic Data
print("6/7 Loading fact_traffic_performance...")
traf_csv = BASE_DIR / "vanet_traffic_data.csv"
if traf_csv.exists():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_traffic_performance (
        traffic_fact_key INTEGER PRIMARY KEY AUTOINCREMENT,
        date_key INTEGER,
        time_key INTEGER,
        segment_key INTEGER,
        telemetry_timestamp TEXT,
        avg_speed_kmph REAL,
        density_veh_per_km REAL,
        avg_wait_time_s REAL,
        occupancy_pct REAL,
        flow_veh_per_hr REAL,
        queue_length_veh REAL,
        avg_accel_ms2 REAL,
        heading_deg REAL,
        signal_state_num REAL,
        incident_num REAL,
        temp_c REAL,
        visibility_km REAL,
        rain_intensity_mmph REAL,
        channel_busy_ratio_pct REAL,
        msg_rate_hz REAL,
        avg_comm_delay_ms REAL,
        rssi_dbm REAL,
        packet_loss_pct REAL,
        speed_density_ratio REAL,
        congestion_pressure REAL,
        wireless_congestion_intensity REAL,
        throughput_per_queued_vehicle REAL,
        acceleration_directionality REAL,
        weather_factor REAL,
        congestion_label TEXT
    );
    """)

    # Populate 500 road segments (S001 to S500)
    seg_rows = [(f"S{i:03d}", f"NH48 Sector {i:03d}", f"Corridor Sector S{i:03d}", f"Sector {(i % 5) + 1}", 2.5, 60.0, 4) for i in range(1, 501)]
    cur.executemany("INSERT OR IGNORE INTO dim_road_segment (road_segment_id, road_name, segment_identifier, corridor_group, length_km, speed_limit_kmph, lanes) VALUES (?,?,?,?,?,?,?)", seg_rows)
    seg_map = dict(cur.execute("SELECT road_segment_id, segment_key FROM dim_road_segment").fetchall())

    chunksize = 25000
    total_loaded = 0
    for chunk in pd.read_csv(traf_csv, chunksize=chunksize, encoding="utf-8", encoding_errors="replace"):
        t_rows = []
        for _, r in chunk.iterrows():
            ts_str = str(r.get("timestamp", "2024-01-01 12:00:00"))
            try:
                dt = pd.to_datetime(ts_str)
                dk = dt.year * 10000 + dt.month * 100 + dt.day
                tk = dt.hour * 100 + dt.minute
            except Exception:
                dk, tk = 20240101, 1200
            
            s_id = str(r.get("road_segment_id", "S001")).strip()
            s_k = seg_map.get(s_id, 1)

            t_rows.append((
                dk, tk, s_k, ts_str,
                float(r.get("avg_speed_kmph", 45.0)),
                float(r.get("density_veh_per_km", 20.0)),
                float(r.get("avg_wait_time_s", 15.0)),
                float(r.get("occupancy_pct", 0.3)),
                float(r.get("flow_veh_per_hr", 1200.0)),
                float(r.get("queue_length_veh", 5.0)),
                float(r.get("avg_accel_ms2", 0.0)),
                float(r.get("heading_deg", 90.0)),
                float(r.get("signal_state_num", 1.0)),
                float(r.get("incident_num", 0.0)),
                float(r.get("temp_c", 28.0)),
                float(r.get("visibility_km", 10.0)),
                float(r.get("rain_intensity_mmph", 0.0)),
                float(r.get("channel_busy_ratio_pct", 25.0)),
                float(r.get("msg_rate_hz", 10.0)),
                float(r.get("avg_comm_delay_ms", 12.0)),
                float(r.get("rssi_dbm", -70.0)),
                float(r.get("packet_loss_pct", 1.0)),
                float(r.get("speed_density_ratio", 2.2)),
                float(r.get("congestion_pressure", 0.4)),
                float(r.get("wireless_congestion_intensity", 0.2)),
                float(r.get("throughput_per_queued_vehicle", 200.0)),
                float(r.get("acceleration_directionality", 0.5)),
                float(r.get("weather_factor", 1.0)),
                str(r.get("label", "moderate")).strip().lower()
            ))

        cur.executemany("""
            INSERT INTO fact_traffic_performance (
                date_key, time_key, segment_key, telemetry_timestamp, avg_speed_kmph, density_veh_per_km,
                avg_wait_time_s, occupancy_pct, flow_veh_per_hr, queue_length_veh, avg_accel_ms2,
                heading_deg, signal_state_num, incident_num, temp_c, visibility_km, rain_intensity_mmph,
                channel_busy_ratio_pct, msg_rate_hz, avg_comm_delay_ms, rssi_dbm, packet_loss_pct,
                speed_density_ratio, congestion_pressure, wireless_congestion_intensity,
                throughput_per_queued_vehicle, acceleration_directionality, weather_factor, congestion_label
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, t_rows)
        total_loaded += len(t_rows)
        if total_loaded >= 50000:
            break
    print(f"Loaded {total_loaded:,} traffic performance records.")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_traf_dk ON fact_traffic_performance(date_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_traf_tk ON fact_traffic_performance(time_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_traf_seg ON fact_traffic_performance(segment_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_traf_c ON fact_traffic_performance(congestion_label);")

# 7. Load Weather
print("7/7 Loading fact_daily_weather...")
wx_csv = BASE_DIR / "india_2000_2024_daily_weather.csv"
if wx_csv.exists():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_daily_weather (
        weather_fact_key INTEGER PRIMARY KEY AUTOINCREMENT,
        date_key INTEGER,
        city TEXT,
        temperature_2m_max REAL,
        temperature_2m_min REAL,
        temperature_2m_mean REAL,
        precipitation_sum_mm REAL,
        rain_sum_mm REAL,
        snowfall_sum_cm REAL,
        precipitation_hours REAL,
        wind_speed_10m_max_kmph REAL,
        wind_gusts_10m_max_kmph REAL,
        wind_direction_10m_dominant_deg REAL,
        shortwave_radiation_sum_mj_m2 REAL,
        et0_fao_evapotranspiration_mm REAL,
        weather_code INTEGER
    );
    """)

    wx_rows = []
    count = 0
    for chunk in pd.read_csv(wx_csv, chunksize=10000, encoding="utf-8", encoding_errors="replace"):
        for _, r in chunk.iterrows():
            dt_str = str(r.get("date", "2024-01-01"))
            try:
                dt = pd.to_datetime(dt_str)
                dk = dt.year * 10000 + dt.month * 100 + dt.day
            except Exception:
                dk = 20240101
            
            city = str(r.get("city", "Pune")).strip()
            tmax = float(r.get("temperature_2m_max", 30.0)) if pd.notna(r.get("temperature_2m_max")) else 30.0
            tmin = float(r.get("temperature_2m_min", 20.0)) if pd.notna(r.get("temperature_2m_min")) else 20.0
            tmean = (tmax + tmin) / 2.0
            precip = float(r.get("precipitation_sum", 0.0)) if pd.notna(r.get("precipitation_sum")) else 0.0
            rain = float(r.get("rain_sum", 0.0)) if pd.notna(r.get("rain_sum")) else 0.0
            wspd = float(r.get("wind_speed_10m_max", 10.0)) if pd.notna(r.get("wind_speed_10m_max")) else 10.0
            wgust = float(r.get("wind_gusts_10m_max", 15.0)) if pd.notna(r.get("wind_gusts_10m_max")) else 15.0
            wdir = float(r.get("wind_direction_10m_dominant", 180.0)) if pd.notna(r.get("wind_direction_10m_dominant")) else 180.0
            wcode = int(r.get("weather_code", 1)) if pd.notna(r.get("weather_code")) else 1

            wx_rows.append((
                dk, city, tmax, tmin, tmean, precip, rain, 0.0, 0.0,
                wspd, wgust, wdir, 15.0, 4.0, wcode
            ))
            count += 1
            if count >= 30000: break
        if count >= 30000: break

    cur.executemany("""
        INSERT INTO fact_daily_weather (
            date_key, city, temperature_2m_max, temperature_2m_min, temperature_2m_mean,
            precipitation_sum_mm, rain_sum_mm, snowfall_sum_cm, precipitation_hours,
            wind_speed_10m_max_kmph, wind_gusts_10m_max_kmph, wind_direction_10m_dominant_deg,
            shortwave_radiation_sum_mj_m2, et0_fao_evapotranspiration_mm, weather_code
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, wx_rows)
    print(f"Loaded {len(wx_rows):,} daily weather records.")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wx_dk ON fact_daily_weather(date_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wx_city ON fact_daily_weather(city);")

# 8. Analytical Views
print("Creating analytical views...")
cur.execute("""
CREATE VIEW IF NOT EXISTS vw_hourly_emergency_risk_profile AS
SELECT t.hour_24, t.time_of_day_bucket, t.is_peak_hour,
       COUNT(a.accident_fact_key) as total_accidents,
       COALESCE(SUM(a.casualties), 0) as total_casualties,
       ROUND(AVG(a.risk_score), 3) as avg_accident_risk,
       COALESCE(SUM(a.is_fatal), 0) as fatal_incidents
FROM dim_time_of_day t
LEFT JOIN fact_road_accidents a ON t.time_key = a.time_key
GROUP BY t.hour_24, t.time_of_day_bucket, t.is_peak_hour;
""")

cur.execute("""
CREATE VIEW IF NOT EXISTS vw_emergency_hospital_readiness AS
SELECT h.hospital_code, h.facility_name, h.facility_type, h.ward_name, h.zone_no,
       h.ownership_class, h.total_beds, h.emergency_beds, h.ambulance_count,
       COUNT(e.ems_fact_key) as total_dispatches,
       COALESCE(SUM(CASE WHEN LOWER(e.triage_priority)='red' THEN 1 ELSE 0 END), 0) as red_priority_cases,
       COALESCE(SUM(CASE WHEN LOWER(e.triage_priority)='yellow' THEN 1 ELSE 0 END), 0) as yellow_priority_cases,
       ROUND(COALESCE(AVG(e.clinical_urgency_score), 0), 2) as avg_urgency_score,
       ROUND(COALESCE(AVG(e.patient_age), 0), 1) as avg_patient_age
FROM dim_hospital h
LEFT JOIN fact_ems_events e ON h.hospital_key = e.hospital_key
GROUP BY h.hospital_code;
""")

cur.execute("""
CREATE VIEW IF NOT EXISTS vw_high_risk_route_corridors AS
SELECT s.road_segment_id, 
       s.segment_identifier,
       s.road_segment_id as road_name,
       'Sector Corridor' as corridor_group,
       s.speed_limit_kmph,
       COUNT(f.traffic_fact_key) as total_telemetry_pings,
       ROUND(AVG(f.avg_speed_kmph), 1) as mean_speed_kmph,
       ROUND(AVG(f.density_veh_per_km), 2) as mean_density_veh_km,
       ROUND(AVG(f.avg_wait_time_s), 1) as mean_wait_time_sec,
       ROUND(AVG(f.congestion_pressure), 4) as mean_congestion_pressure,
       COALESCE(SUM(CASE WHEN LOWER(f.congestion_label)='gridlock' THEN 1 ELSE 0 END), 0) as gridlock_events_count
FROM dim_road_segment s
LEFT JOIN fact_traffic_performance f ON s.segment_key = f.segment_key
GROUP BY s.road_segment_id;
""")

cur.execute("""
CREATE VIEW IF NOT EXISTS vw_weather_accident_correlation AS
SELECT a.weather as weather_condition,
       a.visibility,
       COUNT(a.accident_fact_key) as total_accidents,
       COALESCE(SUM(a.casualties), 0) as total_casualties,
       COALESCE(SUM(a.is_fatal), 0) as fatal_accidents,
       ROUND(AVG(a.risk_score), 3) as avg_risk_score,
       ROUND(AVG(a.vehicles_involved), 2) as avg_vehicles_involved
FROM fact_road_accidents a
GROUP BY a.weather, a.visibility;
""")

conn.commit()
conn.close()
print("Warehouse build complete! All tables and views populated.")
