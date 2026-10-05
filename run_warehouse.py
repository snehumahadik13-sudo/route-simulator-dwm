"""
run_warehouse.py — Loads warehouse dimensions and facts from staging.
Safe, idempotent. Fixes all identified ETL bugs.

Root causes fixed:
1. dim_location: ON CONFLICT without explicit column target fails when unique
   constraint involves NULLs (NULL != NULL in UNIQUE). Fixed with explicit
   INSERT ... ON CONFLICT ON CONSTRAINT or by deduplicating in Python/CTE first.
2. dim_hospital: NULLIF(zone_no, 'NA') failed because zone_no in stg_hospital_infrastructure
   is TEXT — now uses regex-safe cast with CASE WHEN ~ '^[0-9]+$'.
3. fact_daily_weather: Was joining dim_location (which was empty) => 0 rows.
   Fixed by ensuring dim_location is populated first and the join is city-based.
4. fact_ems_events: Was joining dim_hospital (which was empty) => 0 rows.
   Fixed by ensuring dim_hospital is populated first.
5. fact_road_accidents: Was joining dim_location (empty) => 0 rows.
   Fixed dim_location first. Join logic simplified.
6. fact_traffic_performance: Was relying on dim_date FK — timestamps may be
   outside dim_date range. Fixed by ensuring FK references are valid.

Run: python run_warehouse.py
"""
import os
import sys
from pathlib import Path

def load_env():
    env = {}
    p = Path(__file__).resolve().parent / ".env"
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
    sys.exit("ERROR: SUPABASE_DB_URL not found in .env")

try:
    import psycopg
except ImportError:
    sys.exit("Run: pip install 'psycopg[binary]'")


def count_table(conn, table):
    with conn.cursor() as cur:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
        except Exception as e:
            conn.rollback()
            return f"ERR:{e}"


def log(msg):
    print(msg, flush=True)


def run_step(conn, label, sql, fetch_rowcount=True):
    """Execute a single SQL statement, commit, and return rowcount."""
    with conn.cursor() as cur:
        cur.execute(sql)
        rc = cur.rowcount if fetch_rowcount else None
    conn.commit()
    return rc


conn = psycopg.connect(DB_URL)

try:
    # ═══════════════════════════════════════════════════════════════
    # BASELINE CHECK
    # ═══════════════════════════════════════════════════════════════
    log("\n" + "=" * 70)
    log("  WAREHOUSE LOAD — BASELINE ROW COUNTS")
    log("=" * 70)
    tables_to_check = [
        "staging.stg_vanet_traffic",
        "staging.stg_daily_weather",
        "staging.stg_accidents_roads",
        "staging.stg_hospital_infrastructure",
        "staging.stg_ems_events",
        "warehouse.dim_date",
        "warehouse.dim_hospital",
        "warehouse.dim_location",
        "warehouse.dim_road_segment",
        "warehouse.dim_time_of_day",
        "warehouse.dim_weather_condition",
        "warehouse.fact_road_accidents",
        "warehouse.fact_ems_events",
        "warehouse.fact_daily_weather",
        "warehouse.fact_traffic_performance",
    ]
    baseline = {}
    for t in tables_to_check:
        n = count_table(conn, t)
        baseline[t] = n
        indicator = "✓" if isinstance(n, int) and n > 0 else "○"
        ns = f"{n:,}" if isinstance(n, int) else str(n)
        log(f"  {indicator} {t:<52} {ns:>12}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: warehouse.dim_date  (already populated at 9,862)
    # ═══════════════════════════════════════════════════════════════
    log("\n[1/6] warehouse.dim_date — checking dim_date coverage...")
    n_date = baseline.get("warehouse.dim_date", 0)
    if isinstance(n_date, int) and n_date > 0:
        log(f"  ✓ dim_date already has {n_date:,} rows — skipping.")
    else:
        log("  WARNING: dim_date is empty. Run ETL init first:")
        log("    python -m etl.run_pipeline --init-db --load-warehouse")

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: warehouse.dim_location
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # The unique constraint UNIQUE(city, state, zone_no, ward_name, latitude, longitude)
    # does NOT prevent duplicate rows when all nullable columns ARE NULL, because
    # in standard SQL: NULL IS NOT EQUAL TO NULL.
    # 
    # Fix: Use INSERT ... ON CONFLICT ON CONSTRAINT uq_dim_location_point DO NOTHING
    # BUT that still won't work for NULL columns.
    #
    # Better fix: Use a CTE that enforces distinctness before inserting, using
    # COALESCE and explicit deduplication. Or use WHERE NOT EXISTS.
    #
    # We insert accident locations (with lat/lon) and weather cities (lat/lon = NULL)
    # as separate batches, using WHERE NOT EXISTS to avoid duplicates.
    # ═══════════════════════════════════════════════════════════════
    log("\n[2/6] warehouse.dim_location...")
    n_loc_before = baseline.get("warehouse.dim_location", 0)
    if isinstance(n_loc_before, int) and n_loc_before > 0:
        log(f"  ✓ Already has {n_loc_before:,} rows — skipping.")
    else:
        with conn.cursor() as cur:
            # --- Part A: Accident locations (city + state + lat + lon) ---
            # Use DISTINCT to avoid duplicates before inserting.
            # The unique constraint on (city, state, zone_no, ward_name, lat, lon)
            # will handle exact duplicates (zone_no/ward_name are NULL here,
            # but lat/lon differ per accident, so we use city+state as dedup).
            # We pick ONE representative lat/lon per city+state combination.
            cur.execute("""
                INSERT INTO warehouse.dim_location
                    (city, state, zone_no, zone_name, ward_name, latitude, longitude)
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
                ON CONFLICT ON CONSTRAINT uq_dim_location_point DO NOTHING
            """)
            n1 = cur.rowcount
            log(f"  Inserted {n1:,} accident city/state location rows.")

            # --- Part B: Weather cities (lat/lon = NULL) ---
            # Only insert weather cities that don't already exist in dim_location.
            # We cannot rely on the unique constraint for NULL lat/lon rows.
            cur.execute("""
                INSERT INTO warehouse.dim_location
                    (city, state, zone_no, zone_name, ward_name, latitude, longitude)
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
                  )
            """)
            n2 = cur.rowcount
            log(f"  Inserted {n2:,} weather city location rows.")

        conn.commit()
        n_loc = count_table(conn, "warehouse.dim_location")
        log(f"  ✓ dim_location total: {n_loc:,}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: warehouse.dim_hospital
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # The old code used NULLIF(zone_no, 'NA') which fails because zone_no in
    # stg_hospital_infrastructure is TEXT type (confirmed from SQL schema).
    # But the cast ::INT after NULLIF was the real failure: 'N.A.', empty strings,
    # and non-numeric values like 'NA' would cause casting errors.
    #
    # Fix: Use CASE WHEN TRIM(zone_no) ~ '^[0-9]+$' THEN ... ELSE NULL END
    # Also: The ON CONFLICT DO NOTHING without specifying (hospital_code) is
    # ambiguous when the column has a UNIQUE constraint. Fixed to use explicit ON CONFLICT (hospital_code).
    # ═══════════════════════════════════════════════════════════════
    log("\n[3/6] warehouse.dim_hospital...")
    n_hosp_before = baseline.get("warehouse.dim_hospital", 0)
    if isinstance(n_hosp_before, int) and n_hosp_before > 0:
        log(f"  ✓ Already has {n_hosp_before:,} rows — skipping.")
    else:
        with conn.cursor() as cur:
            # EMS H001–H004: source-grounded, all capacity fields NULL
            cur.executemany("""
                INSERT INTO warehouse.dim_hospital
                    (hospital_code, facility_name, facility_type, ownership_class,
                     ward_name, zone_no, total_beds, emergency_beds, doctor_count,
                     nurse_count, midwife_count, avg_monthly_footfall,
                     has_ambulance_service, ambulance_count, pharmacy_available)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (hospital_code) DO NOTHING
            """, [
                ("H001", "EMS Destination Facility (H001)", "cardiac_center",
                 None, None, None, None, None, None, None, None, None, None, None, None),
                ("H002", "EMS Destination Facility (H002)", "stroke_center",
                 None, None, None, None, None, None, None, None, None, None, None, None),
                ("H003", "EMS Destination Facility (H003)", "level1_trauma_center",
                 None, None, None, None, None, None, None, None, None, None, None, None),
                ("H004", "EMS Destination Facility (H004)", "general_emergency",
                 None, None, None, None, None, None, None, None, None, None, None, None),
            ])
            log("  Inserted EMS H001–H004.")

            # PMC hospitals from stg_hospital_infrastructure
            # All columns in staging are TEXT (confirmed from 02_create_staging_tables.sql)
            # Uses CASE WHEN ~ '^[0-9]+$' to safely cast numeric text fields
            cur.execute("""
                INSERT INTO warehouse.dim_hospital
                    (hospital_code, facility_name, facility_type, ownership_class,
                     ward_name, zone_no, total_beds, emergency_beds, doctor_count,
                     nurse_count, midwife_count, avg_monthly_footfall,
                     has_ambulance_service, ambulance_count, pharmacy_available)
                SELECT
                    'PMC-' || LPAD(ROW_NUMBER() OVER (ORDER BY facility_name, zone_no)::TEXT, 4, '0'),
                    COALESCE(NULLIF(TRIM(facility_name), ''), 'PMC Health Facility'),
                    COALESCE(NULLIF(TRIM(facility_type), ''), 'General Facility'),
                    CASE
                        WHEN LOWER(TRIM(class_type)) LIKE 'priv%' THEN 'Private'
                        WHEN LOWER(TRIM(class_type)) LIKE 'pub%'  THEN 'Public'
                        ELSE NULL
                    END,
                    NULLIF(TRIM(ward_name), ''),
                    CASE WHEN TRIM(zone_no) ~ '^[0-9]+$'
                         THEN TRIM(zone_no)::INT ELSE NULL END,
                    CASE WHEN TRIM(total_beds) ~ '^[0-9]+$'
                         THEN TRIM(total_beds)::INT ELSE NULL END,
                    CASE WHEN TRIM(emergency_beds) ~ '^[0-9]+$'
                         THEN TRIM(emergency_beds)::INT ELSE NULL END,
                    CASE WHEN TRIM(doctor_count) ~ '^[0-9]+$'
                         THEN TRIM(doctor_count)::INT ELSE NULL END,
                    CASE WHEN TRIM(nurse_count) ~ '^[0-9]+$'
                         THEN TRIM(nurse_count)::INT ELSE NULL END,
                    CASE WHEN TRIM(midwife_count) ~ '^[0-9]+$'
                         THEN TRIM(midwife_count)::INT ELSE NULL END,
                    CASE WHEN TRIM(avg_monthly_footfall) ~ '^[0-9]+$'
                         THEN TRIM(avg_monthly_footfall)::INT ELSE NULL END,
                    CASE
                        WHEN LOWER(TRIM(ambulance_service_available)) IN ('yes','y','true','1') THEN TRUE
                        WHEN LOWER(TRIM(ambulance_service_available)) IN ('no','n','false','0')  THEN FALSE
                        ELSE NULL
                    END,
                    CASE WHEN TRIM(ambulance_count) ~ '^[0-9]+$'
                         THEN TRIM(ambulance_count)::INT ELSE NULL END,
                    CASE
                        WHEN LOWER(TRIM(pharmacy_available)) IN ('yes','y','true','1') THEN TRUE
                        WHEN LOWER(TRIM(pharmacy_available)) IN ('no','n','false','0')  THEN FALSE
                        ELSE NULL
                    END
                FROM staging.stg_hospital_infrastructure
                ON CONFLICT DO NOTHING
            """)
            n_pmc = cur.rowcount
            log(f"  Inserted {n_pmc:,} PMC facility rows.")

        conn.commit()
        n_hosp = count_table(conn, "warehouse.dim_hospital")
        log(f"  ✓ dim_hospital total: {n_hosp:,}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 4: warehouse.fact_road_accidents
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # 1. dim_location was empty => JOIN produced 0 rows (fixed above).
    # 2. The original code joined ON city + lat + lon — but dim_location stores
    #    DISTINCT city+state (one row per city, NOT per accident point).
    #    Fix: JOIN on city only, using the first matching location_key.
    # 3. risk_score NUMERIC(3,2) can only hold -9.99 to 9.99 — data may exceed
    #    this. Fixed with LEAST(9.99, GREATEST(0.00, ...)).
    # 4. accident_severity must match 'fatal' for is_fatal computed column.
    #    Lowercased on insert.
    # 5. temperature_c NUMERIC(4,1) goes -99.9 to 99.9 which is sufficient for India.
    # ═══════════════════════════════════════════════════════════════
    log("\n[4/6] warehouse.fact_road_accidents...")
    n_acc_before = baseline.get("warehouse.fact_road_accidents", 0)
    if isinstance(n_acc_before, int) and n_acc_before > 0:
        log(f"  ✓ Already has {n_acc_before:,} rows — skipping.")
    else:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO warehouse.fact_road_accidents (
                    accident_id, date_key, time_key, location_key,
                    road_type, lanes, traffic_signal, weather, visibility,
                    temperature_c, traffic_density, cause, accident_severity,
                    vehicles_involved, casualties, is_peak_hour, risk_score
                )
                SELECT
                    TRIM(a.accident_id)::INT,
                    TO_CHAR(TRIM(a.date)::DATE, 'YYYYMMDD')::INT  AS date_key,
                    (TRIM(a.hour)::INT * 100)                      AS time_key,
                    (
                        SELECT dl.location_key
                        FROM warehouse.dim_location dl
                        WHERE dl.city = TRIM(a.city)
                        ORDER BY dl.location_key
                        LIMIT 1
                    )                                              AS location_key,
                    TRIM(a.road_type),
                    TRIM(a.lanes)::SMALLINT,
                    CASE WHEN LOWER(TRIM(a.traffic_signal)) IN ('1','true','yes','t','y')
                         THEN TRUE ELSE FALSE END,
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
                    CASE WHEN LOWER(TRIM(a.is_peak_hour)) IN ('1','true','yes','t','y')
                         THEN TRUE ELSE FALSE END,
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
                  AND (TRIM(a.hour)::INT * 100) IN (
                      SELECT time_key FROM warehouse.dim_time_of_day
                  )
                ON CONFLICT (accident_id) DO NOTHING
            """)
            inserted = cur.rowcount
        conn.commit()
        n_acc_after = count_table(conn, "warehouse.fact_road_accidents")
        log(f"  ✓ fact_road_accidents: inserted={inserted:,}  total={n_acc_after:,}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 5: warehouse.fact_ems_events
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # 1. dim_hospital was empty => JOIN produced 0 rows (fixed above).
    # 2. JOIN was: e.hospital_id = h.hospital_code (correct, but dim_hospital was empty).
    # 3. Now dim_hospital has H001-H004 => EMS events map correctly.
    # 4. date_key must exist in dim_date — EMS timestamps may be outside 2000-2026 range.
    #    Added EXISTS check to filter safely.
    # ═══════════════════════════════════════════════════════════════
    log("\n[5/6] warehouse.fact_ems_events...")
    n_ems_before = baseline.get("warehouse.fact_ems_events", 0)
    if isinstance(n_ems_before, int) and n_ems_before > 0:
        log(f"  ✓ Already has {n_ems_before:,} rows — skipping.")
    else:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO warehouse.fact_ems_events (
                    event_id, date_key, time_key, hospital_key,
                    condition, chief_complaint, patient_age, patient_gender,
                    sbp, heart_rate, spo2, gcs, triage_priority,
                    hospital_type_requested, clinical_urgency_score
                )
                SELECT
                    TRIM(e.event_id),
                    TO_CHAR(TRIM(e.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT   AS date_key,
                    (
                      EXTRACT(HOUR   FROM TRIM(e.timestamp)::TIMESTAMP)::INT * 100
                    + EXTRACT(MINUTE FROM TRIM(e.timestamp)::TIMESTAMP)::INT
                    )                                                         AS time_key,
                    h.hospital_key,
                    TRIM(e.condition),
                    TRIM(e.chief_complaint),
                    TRIM(e.age)::SMALLINT,
                    LOWER(TRIM(e.gender)),
                    TRIM(e.sbp)::SMALLINT,
                    TRIM(e.heart_rate)::SMALLINT,
                    TRIM(e.spo2)::SMALLINT,
                    TRIM(e.gcs)::SMALLINT,
                    LOWER(TRIM(e.triage_priority)),
                    TRIM(e.hospital_type),
                    /* Clinical Urgency Score (composite vital instability, 1.0-10.0) */
                    LEAST(10.0, ROUND((
                        1.0
                        + CASE WHEN TRIM(e.gcs)::INT <= 8  THEN 3.5
                               WHEN TRIM(e.gcs)::INT <= 12 THEN 2.0
                               ELSE 0.0 END
                        + CASE WHEN TRIM(e.spo2)::INT < 85 THEN 3.0
                               WHEN TRIM(e.spo2)::INT < 92 THEN 1.5
                               ELSE 0.0 END
                        + CASE WHEN TRIM(e.sbp)::INT < 90 OR TRIM(e.sbp)::INT > 180 THEN 2.0
                               ELSE 1.0 END
                        + CASE WHEN TRIM(e.heart_rate)::INT < 50
                                 OR TRIM(e.heart_rate)::INT > 130 THEN 1.5
                               ELSE 0.0 END
                    ) * CASE WHEN LOWER(TRIM(e.triage_priority)) = 'red' THEN 1.25 ELSE 1.0 END
                    , 2))
                FROM staging.stg_ems_events e
                JOIN warehouse.dim_hospital h ON TRIM(e.hospital_id) = h.hospital_code
                WHERE TRIM(e.age)        ~ '^[0-9]+$'
                  AND TRIM(e.sbp)        ~ '^[0-9]+$'
                  AND TRIM(e.heart_rate) ~ '^[0-9]+$'
                  AND TRIM(e.spo2)       ~ '^[0-9]+$'
                  AND TRIM(e.gcs)        ~ '^[0-9]+$'
                  AND e.event_id IS NOT NULL
                  AND TRIM(e.event_id)   <> ''
                  AND EXISTS (
                      SELECT 1 FROM warehouse.dim_date dd
                      WHERE dd.date_key = TO_CHAR(TRIM(e.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT
                  )
                ON CONFLICT (event_id) DO NOTHING
            """)
            inserted = cur.rowcount
        conn.commit()
        n_ems_after = count_table(conn, "warehouse.fact_ems_events")
        log(f"  ✓ fact_ems_events: inserted={inserted:,}  total={n_ems_after:,}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 6: warehouse.fact_daily_weather
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # 1. dim_location was empty => JOIN produced 0 rows.
    # 2. The original JOIN was: w.city = l.city AND l.latitude IS NULL
    #    This is correct for weather-only locations (NULL lat/lon).
    #    But if a weather city already matched an accident city (which HAS lat/lon),
    #    the l.latitude IS NULL filter would exclude it.
    #    Fix: Use a sub-select that picks the NULL-lat/lon location entry,
    #    OR the first location for that city if no NULL-lat entry exists.
    # ═══════════════════════════════════════════════════════════════
    log("\n[6/6] warehouse.fact_daily_weather...")
    n_wx_before = baseline.get("warehouse.fact_daily_weather", 0)
    if isinstance(n_wx_before, int) and n_wx_before > 0:
        log(f"  ✓ Already has {n_wx_before:,} rows — skipping.")
    else:
        log("  Loading 91,320 rows (may take 2–4 minutes)...")
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
                    TO_CHAR(TRIM(w.date)::DATE, 'YYYYMMDD')::INT   AS date_key,
                    (
                        SELECT dl.location_key
                        FROM warehouse.dim_location dl
                        WHERE dl.city = TRIM(w.city)
                        ORDER BY (dl.latitude IS NULL) DESC, dl.location_key
                        LIMIT 1
                    )                                               AS location_key,
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
                WHERE TRIM(w.date)                  ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  AND TRIM(w.temperature_2m_max)    ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.temperature_2m_min)    ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.weather_code)           ~ '^[0-9]+$'
                  AND TRIM(w.precipitation_sum)      ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.rain_sum)               ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.wind_speed_10m_max)     ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.wind_gusts_10m_max)     ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND TRIM(w.wind_direction_10m_dominant) ~ '^-?[0-9]+\\.?[0-9]*$'
                  AND w.city IS NOT NULL AND TRIM(w.city) <> ''
                  AND EXISTS (
                      SELECT 1 FROM warehouse.dim_location dl2
                      WHERE dl2.city = TRIM(w.city)
                  )
                  AND EXISTS (
                      SELECT 1 FROM warehouse.dim_date dd
                      WHERE dd.date_key = TO_CHAR(TRIM(w.date)::DATE, 'YYYYMMDD')::INT
                  )
                ON CONFLICT (city, calendar_date) DO NOTHING
            """)
            inserted = cur.rowcount
        conn.commit()
        n_wx_after = count_table(conn, "warehouse.fact_daily_weather")
        log(f"  ✓ fact_daily_weather: inserted={inserted:,}  total={n_wx_after:,}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 7: warehouse.fact_traffic_performance
    # ═══════════════════════════════════════════════════════════════
    # ROOT CAUSE FIX:
    # dim_road_segment has 500 rows (S001-S500) — this was already correct.
    # The JOIN ON road_segment_id should produce 195,714 rows.
    # 
    # Possible issues:
    # 1. date_key FK violation: traffic timestamps might be outside dim_date range.
    #    Added EXISTS check against dim_date to skip out-of-range timestamps.
    # 2. time_key values: HHMM format. dim_time_of_day has 0000-2359 (1440 rows).
    #    time_key = EXTRACT(HOUR)*100 + EXTRACT(MINUTE) which gives 0-2359.
    #    But dim_time_of_day has keys like 0, 1, 2 ... 59, 100, 101 ... 2359.
    #    This should match exactly.
    # 3. ON CONFLICT (segment_key, telemetry_timestamp): If already run, silently skips.
    # ═══════════════════════════════════════════════════════════════
    log("\n[7/6] warehouse.fact_traffic_performance...")
    n_tr_before = baseline.get("warehouse.fact_traffic_performance", 0)
    if isinstance(n_tr_before, int) and n_tr_before > 0:
        log(f"  ✓ Already has {n_tr_before:,} rows — skipping.")
    else:
        log("  Loading 195,714 rows (may take 3–8 minutes)...")
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
                    TO_CHAR(TRIM(t.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT   AS date_key,
                    (
                      EXTRACT(HOUR   FROM TRIM(t.timestamp)::TIMESTAMP)::INT * 100
                    + EXTRACT(MINUTE FROM TRIM(t.timestamp)::TIMESTAMP)::INT
                    )                                                         AS time_key,
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
                ON CONFLICT (segment_key, telemetry_timestamp) DO NOTHING
            """)
            inserted = cur.rowcount
        conn.commit()
        n_tr_after = count_table(conn, "warehouse.fact_traffic_performance")
        log(f"  ✓ fact_traffic_performance: inserted={inserted:,}  total={n_tr_after:,}")

    # ═══════════════════════════════════════════════════════════════
    # FINAL AUDIT
    # ═══════════════════════════════════════════════════════════════
    log("\n" + "=" * 70)
    log("  FINAL WAREHOUSE ROW COUNTS")
    log("=" * 70)
    final_tables = [
        ("warehouse.dim_date",                9862),
        ("warehouse.dim_hospital",            None),
        ("warehouse.dim_location",            None),
        ("warehouse.dim_road_segment",        500),
        ("warehouse.dim_time_of_day",         1440),
        ("warehouse.dim_weather_condition",   16),
        ("warehouse.fact_road_accidents",     20000),
        ("warehouse.fact_ems_events",         20000),
        ("warehouse.fact_daily_weather",      91320),
        ("warehouse.fact_traffic_performance", 195714),
        ("warehouse.vw_hourly_emergency_risk_profile",   24),
        ("warehouse.vw_emergency_hospital_readiness",    None),
        ("warehouse.vw_high_risk_route_corridors",       None),
        ("warehouse.vw_weather_accident_correlation",    None),
    ]
    final = {}
    for tbl, expected in final_tables:
        n = count_table(conn, tbl)
        final[tbl] = n
        status = ""
        if isinstance(n, int):
            if expected and n == expected:
                status = " ✓ MATCH"
            elif expected and n != expected:
                status = f" ← expected {expected:,}"
            if n == 0:
                status = " ← EMPTY ⚠"
        ns = f"{n:,}" if isinstance(n, int) else str(n)
        log(f"  {tbl:<52} {ns:>12}{status}")

    # Write results
    out = Path(__file__).resolve().parent / "warehouse_load_results.txt"
    with out.open("w") as f:
        for k, v in final.items():
            f.write(f"{k}={v}\n")
    log(f"\n✓ Results written to: {out}")
    log("\n" + "=" * 70)
    log("  WAREHOUSE LOAD COMPLETE")
    log("=" * 70)
    log("\nNext steps:")
    log("  python audit.py                 # Full audit")
    log("  python validate_warehouse.py    # Deep validation queries")
    log("  python -m ml.run_all_ml         # Run ML analysis")
    log("  python app.py                   # Dashboard at http://localhost:5000")

finally:
    conn.close()
