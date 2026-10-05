-- =============================================================================
-- olap_queries.sql — OLAP Analysis Queries for Emergency Route Intelligence DW
-- Run from Supabase SQL Editor or psql after warehouse is populated.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. ROLL-UP: Hour → Day → Month → Year (EMS Dispatches)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    d.year,
    d.month,
    d.month_name,
    d.day,
    t.hour_24,
    COUNT(e.ems_fact_key)             AS dispatch_count,
    ROUND(AVG(e.clinical_urgency_score)::NUMERIC, 3) AS avg_urgency,
    SUM(CASE WHEN e.triage_priority = 'red' THEN 1 ELSE 0 END) AS red_cases
FROM warehouse.fact_ems_events e
JOIN warehouse.dim_date        d ON e.date_key = d.date_key
JOIN warehouse.dim_time_of_day t ON e.time_key = t.time_key
GROUP BY ROLLUP(d.year, d.month, d.month_name, d.day, t.hour_24)
ORDER BY d.year NULLS LAST, d.month NULLS LAST, d.day NULLS LAST, t.hour_24 NULLS LAST;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. ROLL-UP: Hour → Day → Month → Year (Road Accidents)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    d.year,
    d.month,
    d.month_name,
    t.hour_24,
    COUNT(a.accident_fact_key)        AS total_accidents,
    SUM(a.casualties)                  AS total_casualties,
    ROUND(AVG(a.risk_score)::NUMERIC, 3) AS avg_risk,
    SUM(CASE WHEN a.is_fatal THEN 1 ELSE 0 END) AS fatal_count
FROM warehouse.fact_road_accidents a
JOIN warehouse.dim_date        d ON a.date_key = d.date_key
JOIN warehouse.dim_time_of_day t ON a.time_key = t.time_key
GROUP BY ROLLUP(d.year, d.month, d.month_name, t.hour_24)
ORDER BY d.year NULLS LAST, d.month NULLS LAST, t.hour_24 NULLS LAST;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. DRILL-DOWN: City → Accident Location (Location dimension + road type)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    l.city,
    l.state,
    a.road_type,
    COUNT(a.accident_fact_key)         AS accidents,
    SUM(a.casualties)                   AS casualties,
    ROUND(AVG(a.risk_score)::NUMERIC, 3) AS avg_risk,
    SUM(CASE WHEN a.is_fatal THEN 1 ELSE 0 END) AS fatal
FROM warehouse.fact_road_accidents a
JOIN warehouse.dim_location l ON a.location_key = l.location_key
GROUP BY CUBE(l.city, l.state, a.road_type)
ORDER BY l.city NULLS LAST, l.state NULLS LAST, accidents DESC NULLS LAST;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. SLICE: Traffic performance during RAIN (weather_code IN (61,63,65,80,81,82))
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    s.road_segment_id,
    COUNT(t.traffic_fact_key)          AS rainy_pings,
    ROUND(AVG(t.avg_speed_kmph)::NUMERIC, 2)      AS mean_speed,
    ROUND(AVG(t.density_veh_per_km)::NUMERIC, 2)  AS mean_density,
    ROUND(AVG(t.avg_wait_time_s)::NUMERIC, 2)     AS mean_wait,
    ROUND(AVG(t.congestion_pressure)::NUMERIC, 4) AS mean_congestion
FROM warehouse.fact_traffic_performance t
JOIN warehouse.dim_road_segment s ON t.segment_key = s.segment_key
WHERE t.rain_intensity_mmph > 0
GROUP BY s.road_segment_id
ORDER BY mean_congestion DESC
LIMIT 20;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. DICE: Weather + Time + Traffic + Accidents (multi-dimensional cross)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    a.weather                          AS accident_weather,
    t.time_of_day_bucket,
    t.is_peak_hour,
    COUNT(a.accident_fact_key)         AS accidents,
    SUM(a.casualties)                   AS casualties,
    ROUND(AVG(a.risk_score)::NUMERIC, 3) AS avg_risk,
    ROUND(AVG(a.temperature_c)::NUMERIC, 1) AS avg_temp
FROM warehouse.fact_road_accidents a
JOIN warehouse.dim_time_of_day t ON a.time_key = t.time_key
GROUP BY a.weather, t.time_of_day_bucket, t.is_peak_hour
ORDER BY accidents DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. High-Risk Segments (from vw_high_risk_route_corridors)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    road_segment_id,
    segment_identifier,
    total_telemetry_pings,
    mean_speed_kmph,
    mean_wait_time_sec,
    mean_congestion_pressure,
    gridlock_events_count
FROM warehouse.vw_high_risk_route_corridors
ORDER BY mean_congestion_pressure DESC
LIMIT 15;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Hourly Emergency Risk Profile (from vw_hourly_emergency_risk_profile)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    hour_24,
    time_of_day_bucket,
    is_peak_hour,
    total_accidents,
    total_casualties,
    avg_accident_risk,
    fatal_incidents
FROM warehouse.vw_hourly_emergency_risk_profile
ORDER BY hour_24;

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Weather ↔ Accident Correlation (from vw_weather_accident_correlation)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    weather_condition,
    visibility,
    total_accidents,
    total_casualties,
    fatal_accidents,
    avg_risk_score,
    avg_vehicles_involved
FROM warehouse.vw_weather_accident_correlation
ORDER BY total_accidents DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Hospital Readiness (from vw_emergency_hospital_readiness)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    hospital_code,
    facility_name,
    facility_type,
    ownership_class,
    total_beds,
    emergency_beds,
    ambulance_count,
    total_dispatches,
    red_priority_cases,
    avg_urgency_score,
    avg_patient_age
FROM warehouse.vw_emergency_hospital_readiness
ORDER BY total_dispatches DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- 10. Monthly Weather Trend — Average Temperature by City
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    w.city,
    d.year,
    d.month,
    d.month_name,
    ROUND(AVG(w.temperature_2m_max)::NUMERIC, 2) AS avg_max_temp,
    ROUND(AVG(w.temperature_2m_min)::NUMERIC, 2) AS avg_min_temp,
    ROUND(SUM(w.precipitation_sum_mm)::NUMERIC, 2) AS total_rain_mm,
    COUNT(*) AS observation_days
FROM warehouse.fact_daily_weather w
JOIN warehouse.dim_date d ON w.date_key = d.date_key
GROUP BY w.city, d.year, d.month, d.month_name
ORDER BY w.city, d.year, d.month;

-- ─────────────────────────────────────────────────────────────────────────────
-- 11. Duplicate check — staging.stg_accidents_roads
-- ─────────────────────────────────────────────────────────────────────────────
SELECT accident_id, COUNT(*) AS cnt
FROM staging.stg_accidents_roads
GROUP BY accident_id
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 10;

-- ─────────────────────────────────────────────────────────────────────────────
-- 12. NULL check — warehouse.fact_ems_events
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN event_id IS NULL THEN 1 ELSE 0 END) AS null_event_id,
    SUM(CASE WHEN date_key IS NULL THEN 1 ELSE 0 END) AS null_date,
    SUM(CASE WHEN hospital_key IS NULL THEN 1 ELSE 0 END) AS null_hospital,
    SUM(CASE WHEN clinical_urgency_score IS NULL THEN 1 ELSE 0 END) AS null_urgency
FROM warehouse.fact_ems_events;

-- ─────────────────────────────────────────────────────────────────────────────
-- 13. Referential integrity — orphaned fact_road_accidents
-- ─────────────────────────────────────────────────────────────────────────────
SELECT COUNT(*) AS orphaned_accidents
FROM warehouse.fact_road_accidents a
WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_location l WHERE l.location_key = a.location_key)
   OR NOT EXISTS (SELECT 1 FROM warehouse.dim_date d WHERE d.date_key = a.date_key);
