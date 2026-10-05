-- =============================================================================
-- fix_warehouse_direct.sql
-- Emergency Route Intelligence Warehouse — Direct SQL Fix Script
-- Run this in Supabase SQL Editor if Python scripts can't connect.
-- Safe and idempotent — uses ON CONFLICT DO NOTHING / WHERE NOT EXISTS.
-- =============================================================================

-- ── STEP 1: Extend dim_date if needed (cover years beyond 2026) ──────────────
-- Already has 9,862 rows covering 2000-2026. Skip if satisfied.
-- If traffic/EMS timestamps go beyond 2026-12-31, extend:
-- (This INSERT is skipped automatically by ON CONFLICT if dates already exist)


-- ── STEP 2: dim_location — Part A: Accident cities ───────────────────────────
-- FIX: Use DISTINCT ON to get one row per city+state before inserting.
-- The old code did DISTINCT city/state/lat/lon (50k+ unique combinations)
-- which overloaded the unique constraint with NULL comparisons.
INSERT INTO warehouse.dim_location
    (city, state, zone_no, zone_name, ward_name, latitude, longitude)
SELECT DISTINCT ON (city, state)
    city,
    state,
    NULL::SMALLINT,
    NULL::VARCHAR,
    NULL::VARCHAR,
    CASE WHEN latitude ~ '^-?[0-9]+\.?[0-9]*$'
         THEN latitude::NUMERIC(9,6) ELSE NULL END,
    CASE WHEN longitude ~ '^-?[0-9]+\.?[0-9]*$'
         THEN longitude::NUMERIC(9,6) ELSE NULL END
FROM staging.stg_accidents_roads
WHERE city IS NOT NULL AND TRIM(city) <> ''
  AND state IS NOT NULL AND TRIM(state) <> ''
ORDER BY city, state, latitude
ON CONFLICT ON CONSTRAINT uq_dim_location_point DO NOTHING;

-- ── STEP 2: dim_location — Part B: Weather cities ────────────────────────────
-- FIX: Use WHERE NOT EXISTS instead of ON CONFLICT (NULL columns not comparable)
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
  );

-- ── STEP 3: dim_hospital — EMS centers H001-H004 ─────────────────────────────
INSERT INTO warehouse.dim_hospital
    (hospital_code, facility_name, facility_type, ownership_class,
     ward_name, zone_no, total_beds, emergency_beds, doctor_count,
     nurse_count, midwife_count, avg_monthly_footfall,
     has_ambulance_service, ambulance_count, pharmacy_available)
VALUES
    ('H001','EMS Destination Facility (H001)','cardiac_center',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),
    ('H002','EMS Destination Facility (H002)','stroke_center',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),
    ('H003','EMS Destination Facility (H003)','level1_trauma_center',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),
    ('H004','EMS Destination Facility (H004)','general_emergency',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)
ON CONFLICT (hospital_code) DO NOTHING;

-- ── STEP 4: dim_hospital — PMC facilities ────────────────────────────────────
-- FIX: All stg_hospital_infrastructure columns are TEXT.
-- Old code: NULLIF(zone_no,'NA')::INT — fails for 'N.A.', '10.0', '', etc.
-- Fix: CASE WHEN TRIM(zone_no) ~ '^[0-9]+$' THEN TRIM(zone_no)::INT ELSE NULL END
INSERT INTO warehouse.dim_hospital
    (hospital_code, facility_name, facility_type, ownership_class,
     ward_name, zone_no, total_beds, emergency_beds, doctor_count,
     nurse_count, midwife_count, avg_monthly_footfall,
     has_ambulance_service, ambulance_count, pharmacy_available)
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
         WHEN LOWER(TRIM(ambulance_service_available)) IN ('no','n','false','0')  THEN FALSE
         ELSE NULL END,
    CASE WHEN TRIM(ambulance_count) ~ '^[0-9]+$' THEN TRIM(ambulance_count)::INT ELSE NULL END,
    CASE WHEN LOWER(TRIM(pharmacy_available)) IN ('yes','y','true','1') THEN TRUE
         WHEN LOWER(TRIM(pharmacy_available)) IN ('no','n','false','0')  THEN FALSE
         ELSE NULL END
FROM staging.stg_hospital_infrastructure
ON CONFLICT DO NOTHING;

-- ── STEP 5: fact_road_accidents ───────────────────────────────────────────────
-- FIX: Original JOIN on exact lat/lon coordinates => 0 matches because dim_location
-- stores ONE row per city+state (not one per accident point).
-- Fix: Use correlated subquery to get first matching location_key for the city.
INSERT INTO warehouse.fact_road_accidents (
    accident_id, date_key, time_key, location_key,
    road_type, lanes, traffic_signal, weather, visibility,
    temperature_c, traffic_density, cause, accident_severity,
    vehicles_involved, casualties, is_peak_hour, risk_score
)
SELECT
    TRIM(a.accident_id)::INT,
    TO_CHAR(TRIM(a.date)::DATE, 'YYYYMMDD')::INT,
    (TRIM(a.hour)::INT * 100),
    (
        SELECT dl.location_key
        FROM warehouse.dim_location dl
        WHERE dl.city = TRIM(a.city)
        ORDER BY dl.location_key
        LIMIT 1
    ),
    TRIM(a.road_type),
    TRIM(a.lanes)::SMALLINT,
    CASE WHEN LOWER(TRIM(a.traffic_signal)) IN ('1','true','yes','t','y') THEN TRUE ELSE FALSE END,
    TRIM(a.weather),
    TRIM(a.visibility),
    CASE WHEN TRIM(a.temperature) ~ '^-?[0-9]+\.?[0-9]*$'
         THEN LEAST(99.9, GREATEST(-99.9, TRIM(a.temperature)::NUMERIC(4,1)))
         ELSE NULL END,
    TRIM(a.traffic_density),
    TRIM(a.cause),
    LOWER(TRIM(a.accident_severity)),
    TRIM(a.vehicles_involved)::SMALLINT,
    TRIM(a.casualties)::SMALLINT,
    CASE WHEN LOWER(TRIM(a.is_peak_hour)) IN ('1','true','yes','t','y') THEN TRUE ELSE FALSE END,
    CASE WHEN TRIM(a.risk_score) ~ '^-?[0-9]+\.?[0-9]*$'
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

-- ── STEP 6: fact_ems_events ───────────────────────────────────────────────────
-- FIX: dim_hospital was empty => JOIN produced 0 rows (fixed by step 3 above).
-- dim_hospital now has H001-H004 => EMS hospital_id maps correctly.
INSERT INTO warehouse.fact_ems_events (
    event_id, date_key, time_key, hospital_key,
    condition, chief_complaint, patient_age, patient_gender,
    sbp, heart_rate, spo2, gcs, triage_priority,
    hospital_type_requested, clinical_urgency_score
)
SELECT
    TRIM(e.event_id),
    TO_CHAR(TRIM(e.timestamp)::TIMESTAMP, 'YYYYMMDD')::INT,
    (
      EXTRACT(HOUR   FROM TRIM(e.timestamp)::TIMESTAMP)::INT * 100
    + EXTRACT(MINUTE FROM TRIM(e.timestamp)::TIMESTAMP)::INT
    ),
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
ON CONFLICT (event_id) DO NOTHING;

-- ── STEP 7: fact_daily_weather ────────────────────────────────────────────────
-- FIX: Original JOIN required dim_location (empty) => 0 rows.
-- FIX: l.latitude IS NULL was too restrictive if cities overlapped.
-- Fix: Correlated subquery to pick best location_key for city.
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
        SELECT dl.location_key
        FROM warehouse.dim_location dl
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
WHERE TRIM(w.date)                  ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  AND TRIM(w.temperature_2m_max)    ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.temperature_2m_min)    ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.weather_code)           ~ '^[0-9]+$'
  AND TRIM(w.precipitation_sum)      ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.rain_sum)               ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.wind_speed_10m_max)     ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.wind_gusts_10m_max)     ~ '^-?[0-9]+\.?[0-9]*$'
  AND TRIM(w.wind_direction_10m_dominant) ~ '^-?[0-9]+\.?[0-9]*$'
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

-- ── STEP 8: fact_traffic_performance ──────────────────────────────────────────
-- dim_road_segment already has 500 rows (S001-S500).
-- FIX: Added date_key validity check to avoid FK violations for out-of-range timestamps.
-- FIX: Added TRIM() to road_segment_id for safety.
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
    (
      EXTRACT(HOUR   FROM TRIM(t.timestamp)::TIMESTAMP)::INT * 100
    + EXTRACT(MINUTE FROM TRIM(t.timestamp)::TIMESTAMP)::INT
    ),
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

-- ── VERIFICATION ─────────────────────────────────────────────────────────────
SELECT 'warehouse.dim_hospital'       AS tbl, COUNT(*) AS rows FROM warehouse.dim_hospital
UNION ALL
SELECT 'warehouse.dim_location',            COUNT(*) FROM warehouse.dim_location
UNION ALL
SELECT 'warehouse.fact_road_accidents',     COUNT(*) FROM warehouse.fact_road_accidents
UNION ALL
SELECT 'warehouse.fact_ems_events',         COUNT(*) FROM warehouse.fact_ems_events
UNION ALL
SELECT 'warehouse.fact_daily_weather',      COUNT(*) FROM warehouse.fact_daily_weather
UNION ALL
SELECT 'warehouse.fact_traffic_performance',COUNT(*) FROM warehouse.fact_traffic_performance
UNION ALL
SELECT 'vw_emergency_hospital_readiness',   COUNT(*) FROM warehouse.vw_emergency_hospital_readiness
UNION ALL
SELECT 'vw_high_risk_route_corridors',      COUNT(*) FROM warehouse.vw_high_risk_route_corridors
UNION ALL
SELECT 'vw_weather_accident_correlation',   COUNT(*) FROM warehouse.vw_weather_accident_correlation
ORDER BY tbl;
