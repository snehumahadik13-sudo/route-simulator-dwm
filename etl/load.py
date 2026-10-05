import datetime
from typing import Dict, List, Any
from .config import BATCH_SIZE
from .transform import (
    EMS_HOSPITALS,
    get_segment_metadata,
    transform_traffic_row,
    transform_weather_row,
    transform_accident_row,
    transform_ems_row,
    transform_pmc_hospital_row,
    clean_str,
    clean_int,
    clean_float,
    clean_bool
)

# -----------------------------------------------------------------------------
# Dimension Loaders
# -----------------------------------------------------------------------------

def load_dim_date(conn, start_year: int = 2000, end_year: int = 2026):
    """Generates and populates conformed calendar dimension from start_year to end_year."""
    print("Populating warehouse.dim_date...")
    start_date = datetime.date(start_year, 1, 1)
    end_date = datetime.date(end_year, 12, 31)
    delta = datetime.timedelta(days=1)
    
    rows = []
    curr = start_date
    while curr <= end_date:
        date_key = curr.year * 10000 + curr.month * 100 + curr.day
        day_of_week = curr.strftime("%A")
        day_of_week_num = curr.isoweekday() # 1=Monday, 7=Sunday
        is_weekend = day_of_week_num in (6, 7)
        quarter = (curr.month - 1) // 3 + 1
        month_name = curr.strftime("%B")
        
        rows.append((
            date_key,
            curr,
            curr.year,
            quarter,
            curr.month,
            month_name,
            curr.day,
            day_of_week,
            day_of_week_num,
            is_weekend,
            None # festival populated from genuine source values where present
        ))
        curr += delta
        
    sql = """
        INSERT INTO warehouse.dim_date (
            date_key, calendar_date, year, quarter, month, month_name, 
            day, day_of_week, day_of_week_num, is_weekend, festival
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date_key) DO NOTHING;
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    print(f"Loaded {len(rows):,} date records into warehouse.dim_date.")

def load_dim_time(conn):
    """Populates 1,440 minutes of the day into warehouse.dim_time_of_day."""
    print("Populating warehouse.dim_time_of_day...")
    rows = []
    for h in range(24):
        for m in range(60):
            time_key = h * 100 + m
            time_val = datetime.time(h, m)
            
            # Standard peak traffic window: Morning (8:00 - 11:59) and Evening (17:00 - 20:59)
            is_peak = (8 <= h <= 11) or (17 <= h <= 20)
            
            if 0 <= h < 6:
                bucket = "Night"
            elif 6 <= h < 12:
                bucket = "Morning Peak" if (8 <= h <= 11) else "Early Morning"
            elif 12 <= h < 17:
                bucket = "Midday"
            elif 17 <= h < 21:
                bucket = "Evening Peak"
            else:
                bucket = "Late Evening"
                
            rows.append((time_key, time_val, h, m, bucket, is_peak))
            
    sql = """
        INSERT INTO warehouse.dim_time_of_day (
            time_key, time_value, hour_24, minute, time_of_day_bucket, is_peak_hour
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (time_key) DO NOTHING;
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    print(f"Loaded {len(rows):,} time intervals into warehouse.dim_time_of_day.")

def load_dim_weather_conditions(conn):
    """Populates standard WMO weather codes and classifications."""
    print("Populating warehouse.dim_weather_condition...")
    wmo_codes = [
        (0, "Clear Sky", "High (>8km)", "None"),
        (1, "Mainly Clear", "High (>8km)", "None"),
        (2, "Partly Cloudy", "High (>8km)", "None"),
        (3, "Overcast", "Moderate (4-8km)", "None"),
        (45, "Fog", "Low (<4km)", "None"),
        (48, "Depositing Rime Fog", "Low (<4km)", "None"),
        (51, "Light Drizzle", "Moderate (4-8km)", "Light"),
        (53, "Moderate Drizzle", "Moderate (4-8km)", "Moderate"),
        (55, "Dense Drizzle", "Low (<4km)", "Moderate"),
        (61, "Slight Rain", "Moderate (4-8km)", "Light"),
        (63, "Moderate Rain", "Moderate (4-8km)", "Moderate"),
        (65, "Heavy Rain", "Low (<4km)", "Heavy"),
        (80, "Slight Rain Showers", "Moderate (4-8km)", "Light"),
        (81, "Moderate Rain Showers", "Low (<4km)", "Moderate"),
        (82, "Violent Rain Showers", "Low (<4km)", "Heavy"),
        (95, "Thunderstorm", "Low (<4km)", "Heavy")
    ]
    sql = """
        INSERT INTO warehouse.dim_weather_condition (
            weather_code, condition_name, visibility_category, rain_category
        ) VALUES (%s, %s, %s, %s)
        ON CONFLICT (weather_code) DO NOTHING;
    """
    with conn.cursor() as cur:
        cur.executemany(sql, wmo_codes)
    conn.commit()
    print("Loaded meteorological classifications into warehouse.dim_weather_condition.")

def load_dim_road_segments(conn):
    """
    Populates 500 VANET road segments strictly using source identifiers S001-S500.
    Non-source attributes (road_name, corridor_group, lanes, etc.) are NULL by default.
    """
    print("Populating warehouse.dim_road_segment (strict source identifiers S001-S500)...")
    rows = []
    for i in range(1, 501):
        seg_id = f"S{i:03d}"
        rows.append((
            seg_id,
            None, # road_name (NULL, not present in vanet_traffic_data.csv)
            None, # corridor_group (NULL, not present in vanet_traffic_data.csv)
            None, # road_type (NULL)
            None, # lanes (NULL)
            None, # has_traffic_signal (NULL)
            None  # speed_limit_kmph (NULL)
        ))
        
    sql = """
        INSERT INTO warehouse.dim_road_segment (
            road_segment_id, road_name, corridor_group, road_type, lanes, 
            has_traffic_signal, speed_limit_kmph
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (road_segment_id) DO NOTHING;
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    print(f"Loaded {len(rows):,} genuine segment IDs into warehouse.dim_road_segment.")

def load_dim_hospitals(conn):
    """
    Populates hospital dimension strictly from source evidence:
    1. The 4 EMS destination centers (H001-H004) with exact source-reported hospital_type (capacities NULL).
    2. The 737 genuine municipal healthcare facilities from PMC Hospital Infrastructure.
    """
    print("Populating warehouse.dim_hospital (strict source evidence)...")
    
    # 1. Insert EMS destination centers with source-reported hospital_type
    ems_rows = []
    for code, h in EMS_HOSPITALS.items():
        ems_rows.append((
            code,
            h["facility_name"],
            h["facility_type"],
            h["ownership_class"],
            h["ward_name"],
            h["zone_no"],
            h["total_beds"],
            h["emergency_beds"],
            h["doctor_count"],
            h["nurse_count"],
            h["midwife_count"],
            h["avg_monthly_footfall"],
            h["has_ambulance_service"],
            h["ambulance_count"],
            h["pharmacy_available"]
        ))
        
    sql_ems = """
        INSERT INTO warehouse.dim_hospital (
            hospital_code, facility_name, facility_type, ownership_class,
            ward_name, zone_no, total_beds, emergency_beds, doctor_count,
            nurse_count, midwife_count, avg_monthly_footfall,
            has_ambulance_service, ambulance_count, pharmacy_available
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (hospital_code) DO NOTHING;
    """
    with conn.cursor() as cur:
        cur.executemany(sql_ems, ems_rows)
        
    # 2. Insert genuine PMC facilities from staging with real reported attributes.
    # FIX: All columns in stg_hospital_infrastructure are TEXT (per 02_create_staging_tables.sql).
    # The original NULLIF(zone_no, 'NA')::INT fails when zone_no contains 'N.A.', '', etc.
    # Use CASE WHEN ~ '^[0-9]+$' to safely cast only pure-numeric strings.
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouse.dim_hospital (
                hospital_code, facility_name, facility_type, ownership_class,
                ward_name, zone_no, total_beds, emergency_beds, doctor_count,
                nurse_count, midwife_count, avg_monthly_footfall,
                has_ambulance_service, ambulance_count, pharmacy_available
            )
            SELECT 
                'PMC-' || LPAD(ROW_NUMBER() OVER (ORDER BY facility_name, zone_no)::TEXT, 4, '0'),
                COALESCE(NULLIF(TRIM(facility_name), ''), 'PMC Health Facility'),
                COALESCE(NULLIF(TRIM(facility_type), ''), 'General Facility'),
                CASE WHEN LOWER(TRIM(class_type)) LIKE 'priv%' THEN 'Private'
                     WHEN LOWER(TRIM(class_type)) LIKE 'pub%'  THEN 'Public'
                     ELSE NULL END,
                NULLIF(TRIM(ward_name), ''),
                CASE WHEN TRIM(zone_no) ~ '^[0-9]+$' THEN TRIM(zone_no)::INT ELSE NULL END,
                CASE WHEN TRIM(total_beds) ~ '^[0-9]+$' THEN TRIM(total_beds)::INT ELSE NULL END,
                CASE WHEN TRIM(emergency_beds) ~ '^[0-9]+$' THEN TRIM(emergency_beds)::INT ELSE NULL END,
                CASE WHEN TRIM(doctor_count) ~ '^[0-9]+$' THEN TRIM(doctor_count)::INT ELSE NULL END,
                CASE WHEN TRIM(nurse_count) ~ '^[0-9]+$' THEN TRIM(nurse_count)::INT ELSE NULL END,
                CASE WHEN TRIM(midwife_count) ~ '^[0-9]+$' THEN TRIM(midwife_count)::INT ELSE NULL END,
                CASE WHEN TRIM(avg_monthly_footfall) ~ '^[0-9]+$' THEN TRIM(avg_monthly_footfall)::INT ELSE NULL END,
                CASE WHEN LOWER(TRIM(ambulance_service_available)) IN ('yes','y','true','1') THEN TRUE
                     WHEN LOWER(TRIM(ambulance_service_available)) IN ('no','n','false','0') THEN FALSE
                     ELSE NULL END,
                CASE WHEN TRIM(ambulance_count) ~ '^[0-9]+$' THEN TRIM(ambulance_count)::INT ELSE NULL END,
                CASE WHEN LOWER(TRIM(pharmacy_available)) IN ('yes','y','true','1') THEN TRUE
                     WHEN LOWER(TRIM(pharmacy_available)) IN ('no','n','false','0') THEN FALSE
                     ELSE NULL END
            FROM staging.stg_hospital_infrastructure
            ON CONFLICT DO NOTHING;
        """)
    conn.commit()
    print("Loaded genuine PMC hospital facilities into warehouse.dim_hospital.")

def load_dim_locations(conn):
    """Extracts and populates unique cities, states, and coordinates from source data.
    
    FIX: The unique constraint UNIQUE(city, state, zone_no, ward_name, latitude, longitude)
    does NOT block duplicate rows when nullable columns are ALL NULL (NULL != NULL in SQL).
    Strategy:
    - For accident cities: use DISTINCT ON (city, state) to pick one representative row.
    - For weather cities: use WHERE NOT EXISTS to avoid duplicates with NULL lat/lon.
    """
    print("Populating warehouse.dim_location...")
    with conn.cursor() as cur:
        # Location records from accidents dataset — one row per distinct city+state
        cur.execute("""
            INSERT INTO warehouse.dim_location (
                city, state, zone_no, zone_name, ward_name, latitude, longitude
            )
            SELECT DISTINCT ON (city, state)
                city,
                state,
                NULL::SMALLINT,
                NULL::VARCHAR,
                NULL::VARCHAR,
                CASE WHEN latitude ~ '^-?[0-9]+\\.?[0-9]*$'
                     THEN latitude::NUMERIC(9,6) ELSE NULL END,
                CASE WHEN longitude ~ '^-?[0-9]+\\.?[0-9]*$'
                     THEN longitude::NUMERIC(9,6) ELSE NULL END
            FROM staging.stg_accidents_roads
            WHERE city IS NOT NULL AND TRIM(city) <> ''
              AND state IS NOT NULL AND TRIM(state) <> ''
            ORDER BY city, state, latitude
            ON CONFLICT ON CONSTRAINT uq_dim_location_point DO NOTHING;
        """)
        
        # Weather cities: only insert cities not already present with NULL lat/lon
        # Cannot use ON CONFLICT for NULL-col constraints, so use WHERE NOT EXISTS
        cur.execute("""
            INSERT INTO warehouse.dim_location (
                city, state, zone_no, zone_name, ward_name, latitude, longitude
            )
            SELECT DISTINCT
                w.city,
                'India'::VARCHAR,
                NULL::SMALLINT,
                NULL::VARCHAR,
                NULL::VARCHAR,
                NULL::NUMERIC(9,6),
                NULL::NUMERIC(9,6)
            FROM staging.stg_daily_weather w
            WHERE w.city IS NOT NULL AND TRIM(w.city) <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM warehouse.dim_location dl
                  WHERE dl.city = TRIM(w.city)
                    AND dl.latitude IS NULL
              );
        """)
    conn.commit()
    print("Loaded geographical coordinates and cities into warehouse.dim_location.")

# -----------------------------------------------------------------------------
# Fact Table Loaders
# -----------------------------------------------------------------------------

def load_fact_accidents(conn):
    """Loads and transforms road accidents into warehouse.fact_road_accidents.
    
    FIX: Original JOIN on a.latitude = l.latitude AND a.longitude = l.longitude
    broke because dim_location stores ONE row per city+state (not per accident point).
    Simplified to city-based lookup using a correlated subquery.
    Also fixed: risk_score NUMERIC(3,2) clamped to 0.00-9.99.
    """
    print("Loading warehouse.fact_road_accidents (accident incidents only)...")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouse.fact_road_accidents (
                accident_id, date_key, time_key, location_key, road_type,
                lanes, traffic_signal, weather, visibility, temperature_c,
                traffic_density, cause, accident_severity, vehicles_involved,
                casualties, is_peak_hour, risk_score
            )
            SELECT 
                TRIM(a.accident_id)::INT,
                TO_CHAR(TRIM(a.date)::DATE, 'YYYYMMDD')::INT,
                (TRIM(a.hour)::INT * 100),
                (
                    SELECT dl.location_key FROM warehouse.dim_location dl
                    WHERE dl.city = TRIM(a.city)
                    ORDER BY dl.location_key LIMIT 1
                ),
                TRIM(a.road_type),
                TRIM(a.lanes)::SMALLINT,
                CASE WHEN LOWER(TRIM(a.traffic_signal)) IN ('1','true','yes','t','y') THEN TRUE ELSE FALSE END,
                TRIM(a.weather),
                TRIM(a.visibility),
                CASE WHEN TRIM(a.temperature) ~ '^-?[0-9]+\\.?[0-9]*$'
                     THEN LEAST(99.9, GREATEST(-99.9, TRIM(a.temperature)::NUMERIC(4,1)))
                     ELSE NULL END,
                TRIM(a.traffic_density),
                TRIM(a.cause),
                LOWER(TRIM(a.accident_severity)),
                TRIM(a.vehicles_involved)::SMALLINT,
                TRIM(a.casualties)::SMALLINT,
                CASE WHEN LOWER(TRIM(a.is_peak_hour)) IN ('1','true','yes','t','y') THEN TRUE ELSE FALSE END,
                CASE WHEN TRIM(a.risk_score) ~ '^-?[0-9]+\\.?[0-9]*$'
                     THEN LEAST(9.99, GREATEST(0.00, TRIM(a.risk_score)::NUMERIC(3,2)))
                     ELSE 0.00 END
            FROM staging.stg_accidents_roads a
            WHERE TRIM(a.accident_id)       ~ '^[0-9]+$'
              AND TRIM(a.hour)              ~ '^[0-9]+$'
              AND TRIM(a.lanes)             ~ '^[0-9]+$'
              AND TRIM(a.vehicles_involved) ~ '^[0-9]+$'
              AND TRIM(a.casualties)        ~ '^[0-9]+$'
              AND TRIM(a.date)              ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              AND TRIM(a.city)              IS NOT NULL
              AND TRIM(a.city)              <> ''
              AND EXISTS (
                  SELECT 1 FROM warehouse.dim_location dl2
                  WHERE dl2.city = TRIM(a.city)
              )
              AND EXISTS (
                  SELECT 1 FROM warehouse.dim_date dd
                  WHERE dd.date_key = TO_CHAR(TRIM(a.date)::DATE, 'YYYYMMDD')::INT
              )
            ON CONFLICT (accident_id) DO NOTHING;
        """)
        inserted = cur.rowcount
    conn.commit()
    print(f"Loaded {inserted:,} records into warehouse.fact_road_accidents.")

def load_fact_ems_events(conn):
    """Loads and transforms EMS events into warehouse.fact_ems_events."""
    print("Loading warehouse.fact_ems_events...")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouse.fact_ems_events (
                event_id, date_key, time_key, hospital_key, condition,
                chief_complaint, patient_age, patient_gender, sbp,
                heart_rate, spo2, gcs, triage_priority,
                hospital_type_requested, clinical_urgency_score
            )
            SELECT 
                e.event_id,
                TO_CHAR(e.timestamp::TIMESTAMP, 'YYYYMMDD')::INT,
                EXTRACT(HOUR FROM e.timestamp::TIMESTAMP)::INT * 100 + EXTRACT(MINUTE FROM e.timestamp::TIMESTAMP)::INT,
                h.hospital_key,
                e.condition,
                e.chief_complaint,
                e.age::SMALLINT,
                LOWER(e.gender),
                e.sbp::SMALLINT,
                e.heart_rate::SMALLINT,
                e.spo2::SMALLINT,
                e.gcs::SMALLINT,
                e.triage_priority,
                e.hospital_type,
                ROUND(
                    (1.0 + 
                     CASE WHEN e.gcs::INT <= 8 THEN 3.5 WHEN e.gcs::INT <= 12 THEN 2.0 ELSE 0.0 END +
                     CASE WHEN e.spo2::INT < 85 THEN 3.0 WHEN e.spo2::INT < 92 THEN 1.5 ELSE 0.0 END +
                     CASE WHEN e.sbp::INT < 90 OR e.sbp::INT > 180 THEN 2.0 ELSE 1.0 END +
                     CASE WHEN e.heart_rate::INT < 50 OR e.heart_rate::INT > 130 THEN 1.5 ELSE 0.0 END
                    ) * CASE WHEN LOWER(e.triage_priority) = 'red' THEN 1.25 ELSE 1.0 END
                , 2)
            FROM staging.stg_ems_events e
            JOIN warehouse.dim_hospital h ON e.hospital_id = h.hospital_code
            ON CONFLICT (event_id) DO NOTHING;
        """)
        inserted = cur.rowcount
    conn.commit()
    print(f"Loaded {inserted:,} records into warehouse.fact_ems_events.")

def load_fact_daily_weather(conn):
    """Loads daily weather into warehouse.fact_daily_weather.
    
    FIX: Original JOIN required dim_location to be populated first (fixed in run order).
    Also: the l.latitude IS NULL filter was too restrictive — if a weather city
    matches an accident city that HAS lat/lon, the weather city's NULL-lat entry
    may not have been inserted. Fixed with a correlated subquery that picks the
    best location_key (preferring NULL-lat entry, falling back to any city match).
    """
    print("Loading warehouse.fact_daily_weather...")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouse.fact_daily_weather (
                date_key, location_key, city, calendar_date,
                temperature_2m_max, temperature_2m_min,
                apparent_temperature_max, apparent_temperature_min,
                precipitation_sum_mm, rain_sum_mm, weather_code,
                wind_speed_10m_max_kmph, wind_gusts_10m_max_kmph,
                wind_direction_dominant_deg
            )
            SELECT 
                TO_CHAR(TRIM(w.date)::DATE, 'YYYYMMDD')::INT,
                (
                    SELECT dl.location_key FROM warehouse.dim_location dl
                    WHERE dl.city = TRIM(w.city)
                    ORDER BY (dl.latitude IS NULL) DESC, dl.location_key
                    LIMIT 1
                ),
                TRIM(w.city),
                TRIM(w.date)::DATE,
                TRIM(w.temperature_2m_max)::NUMERIC(5,2),
                TRIM(w.temperature_2m_min)::NUMERIC(5,2),
                TRIM(w.apparent_temperature_max)::NUMERIC(5,2),
                TRIM(w.apparent_temperature_min)::NUMERIC(5,2),
                GREATEST(0.0, TRIM(w.precipitation_sum)::NUMERIC(6,2)),
                GREATEST(0.0, TRIM(w.rain_sum)::NUMERIC(6,2)),
                TRIM(w.weather_code)::SMALLINT,
                TRIM(w.wind_speed_10m_max)::NUMERIC(5,2),
                TRIM(w.wind_gusts_10m_max)::NUMERIC(5,2),
                TRIM(w.wind_direction_10m_dominant)::NUMERIC(5,1)
            FROM staging.stg_daily_weather w
            WHERE TRIM(w.date)               ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              AND TRIM(w.temperature_2m_max) ~ '^-?[0-9]+\\.?[0-9]*$'
              AND TRIM(w.temperature_2m_min) ~ '^-?[0-9]+\\.?[0-9]*$'
              AND TRIM(w.weather_code)        ~ '^[0-9]+$'
              AND TRIM(w.precipitation_sum)   ~ '^-?[0-9]+\\.?[0-9]*$'
              AND w.city IS NOT NULL AND TRIM(w.city) <> ''
              AND EXISTS (
                  SELECT 1 FROM warehouse.dim_location dl2
                  WHERE dl2.city = TRIM(w.city)
              )
              AND EXISTS (
                  SELECT 1 FROM warehouse.dim_date dd
                  WHERE dd.date_key = TO_CHAR(TRIM(w.date)::DATE, 'YYYYMMDD')::INT
              )
            ON CONFLICT (city, calendar_date) DO NOTHING;
        """)
        inserted = cur.rowcount
    conn.commit()
    print(f"Loaded {inserted:,} records into warehouse.fact_daily_weather.")

def load_fact_traffic_performance(conn):
    """Loads sensor telemetry into warehouse.fact_traffic_performance.
    
    FIX: Added EXISTS filter against dim_date to avoid FK violations for timestamps
    outside the 2000-2026 dim_date range. Also added TRIM() to road_segment_id
    to ensure the JOIN matches.
    """
    print("Loading warehouse.fact_traffic_performance...")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO warehouse.fact_traffic_performance (
                date_key, time_key, segment_key, telemetry_timestamp,
                avg_speed_kmph, density_veh_per_km, avg_wait_time_s,
                occupancy_pct, flow_veh_per_hr, queue_length_veh,
                avg_accel_ms2, heading_deg, signal_state_num,
                incident_num, temp_c, visibility_km, rain_intensity_mmph,
                channel_busy_ratio_pct, msg_rate_hz, avg_comm_delay_ms,
                rssi_dbm, packet_loss_pct, speed_density_ratio,
                congestion_pressure, wireless_congestion_intensity,
                throughput_per_queued_vehicle, acceleration_directionality,
                weather_factor, congestion_label
            )
            SELECT 
                TO_CHAR(TRIM(t.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT,
                EXTRACT(HOUR FROM TRIM(t.timestamp)::TIMESTAMP)::INT * 100
                  + EXTRACT(MINUTE FROM TRIM(t.timestamp)::TIMESTAMP)::INT,
                s.segment_key,
                TRIM(t.timestamp)::TIMESTAMP,
                t.avg_speed_kmph::NUMERIC(6,2),
                t.density_veh_per_km::NUMERIC(6,2),
                GREATEST(0.0, t.avg_wait_time_s::NUMERIC(6,2)),
                LEAST(100.0, GREATEST(0.0, t.occupancy_pct::NUMERIC(6,2))),
                t.flow_veh_per_hr::NUMERIC(8,2),
                GREATEST(0.0, t.queue_length_veh::NUMERIC(6,2)),
                t.avg_accel_ms2::NUMERIC(6,3),
                t.heading_deg::NUMERIC(6,2),
                t.signal_state_num::NUMERIC(5,3),
                GREATEST(0.0, t.incident_num::NUMERIC(5,3)),
                t.temp_c::NUMERIC(5,2),
                GREATEST(0.0, t.visibility_km::NUMERIC(5,2)),
                GREATEST(0.0, t.rain_intensity_mmph::NUMERIC(5,2)),
                t.channel_busy_ratio_pct::NUMERIC(5,2),
                t.msg_rate_hz::NUMERIC(5,2),
                t.avg_comm_delay_ms::NUMERIC(6,2),
                t.rssi_dbm::NUMERIC(6,2),
                t.packet_loss_pct::NUMERIC(5,2),
                t.speed_density_ratio::NUMERIC(8,4),
                GREATEST(0.0, t.congestion_pressure::NUMERIC(8,4)),
                GREATEST(0.0, t.wireless_congestion_intensity::NUMERIC(8,4)),
                GREATEST(0.0, t.throughput_per_queued_vehicle::NUMERIC(10,4)),
                t.acceleration_directionality::NUMERIC(8,4),
                t.weather_factor::NUMERIC(8,4),
                TRIM(t.label)
            FROM staging.stg_vanet_traffic t
            JOIN warehouse.dim_road_segment s ON TRIM(t.road_segment_id) = s.road_segment_id
            WHERE EXISTS (
                SELECT 1 FROM warehouse.dim_date dd
                WHERE dd.date_key = TO_CHAR(TRIM(t.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT
            )
            ON CONFLICT (segment_key, telemetry_timestamp) DO NOTHING;
        """)
        inserted = cur.rowcount
    conn.commit()
    print(f"Loaded {inserted:,} records into warehouse.fact_traffic_performance.")
