-- =============================================================================
-- Emergency Route Intelligence Warehouse (DWM Project)
-- Script 05: Analytical Views & Marts (Strict Data Integrity Version)
-- Database Target: PostgreSQL / Cloud Supabase
-- =============================================================================

-- -----------------------------------------------------------------------------
-- View 1: Emergency Hospital Readiness & Dispatch Load
-- Analyzes hospital workload, specialized capacity vs incoming EMS triage urgency
-- Handles NULLs gracefully where capacities are not recorded in source
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.vw_emergency_hospital_readiness AS
SELECT 
    h.hospital_code,
    h.facility_name,
    h.facility_type,
    h.ownership_class,
    h.total_beds,
    h.emergency_beds,
    h.ambulance_count,
    COUNT(e.ems_fact_key) AS total_dispatches,
    SUM(CASE WHEN e.triage_priority = 'red' THEN 1 ELSE 0 END) AS red_priority_cases,
    SUM(CASE WHEN e.triage_priority = 'yellow' THEN 1 ELSE 0 END) AS yellow_priority_cases,
    ROUND(AVG(e.clinical_urgency_score), 2) AS avg_urgency_score,
    ROUND(AVG(e.patient_age), 1) AS avg_patient_age
FROM warehouse.dim_hospital h
LEFT JOIN warehouse.fact_ems_events e ON h.hospital_key = e.hospital_key
GROUP BY 
    h.hospital_code, h.facility_name, h.facility_type, 
    h.ownership_class, h.total_beds, h.emergency_beds, h.ambulance_count;

-- -----------------------------------------------------------------------------
-- View 2: High Risk Route Corridors
-- Analyzes sensor congestion intensity, telemetry flow, and wait times per segment
-- Uses genuine source segment IDs (S001 - S500)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.vw_high_risk_route_corridors AS
SELECT 
    r.road_segment_id,
    COALESCE(r.road_name, 'Road Segment ' || r.road_segment_id) AS segment_identifier,
    r.corridor_group,
    COUNT(t.traffic_fact_key) AS total_telemetry_pings,
    ROUND(AVG(t.avg_speed_kmph), 2) AS mean_speed_kmph,
    ROUND(AVG(t.density_veh_per_km), 2) AS mean_density_veh_km,
    ROUND(AVG(t.avg_wait_time_s), 2) AS mean_wait_time_sec,
    ROUND(AVG(t.congestion_pressure), 2) AS mean_congestion_pressure,
    SUM(CASE WHEN t.congestion_label = 'Gridlock' THEN 1 ELSE 0 END) AS gridlock_events_count
FROM warehouse.dim_road_segment r
JOIN warehouse.fact_traffic_performance t ON r.segment_key = t.segment_key
GROUP BY 
    r.road_segment_id, r.road_name, r.corridor_group;

-- -----------------------------------------------------------------------------
-- View 3: Weather Impact on Accident Casualties & Severity
-- Correlates accident severity and risk score with atmospheric conditions
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.vw_weather_accident_correlation AS
SELECT 
    a.weather AS weather_condition,
    a.visibility,
    COUNT(a.accident_fact_key) AS total_accidents,
    SUM(a.casualties) AS total_casualties,
    SUM(CASE WHEN a.is_fatal THEN 1 ELSE 0 END) AS fatal_accidents,
    ROUND(AVG(a.risk_score), 3) AS avg_risk_score,
    ROUND(AVG(a.vehicles_involved), 2) AS avg_vehicles_involved
FROM warehouse.fact_road_accidents a
GROUP BY a.weather, a.visibility;

-- -----------------------------------------------------------------------------
-- View 4: Hourly Emergency Risk Profile
-- Aggregates peak hour accident distributions and casualty rates
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW warehouse.vw_hourly_emergency_risk_profile AS
SELECT 
    t.hour_24,
    t.time_of_day_bucket,
    t.is_peak_hour,
    COUNT(a.accident_fact_key) AS total_accidents,
    SUM(a.casualties) AS total_casualties,
    ROUND(AVG(a.risk_score), 3) AS avg_accident_risk,
    SUM(CASE WHEN a.is_fatal THEN 1 ELSE 0 END) AS fatal_incidents
FROM warehouse.dim_time_of_day t
LEFT JOIN warehouse.fact_road_accidents a ON t.time_key = a.time_key
GROUP BY t.hour_24, t.time_of_day_bucket, t.is_peak_hour
ORDER BY t.hour_24;
