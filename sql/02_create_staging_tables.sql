-- =============================================================================
-- Emergency Route Intelligence Warehouse (DWM Project)
-- Script 02: Staging Layer Tables
-- Database Target: PostgreSQL / Cloud Supabase
-- =============================================================================

-- Staging 1: VANET Traffic Telemetry
CREATE TABLE IF NOT EXISTS staging.stg_vanet_traffic (
    timestamp TEXT,
    road_segment_id TEXT,
    avg_speed_kmph TEXT,
    density_veh_per_km TEXT,
    avg_wait_time_s TEXT,
    occupancy_pct TEXT,
    flow_veh_per_hr TEXT,
    queue_length_veh TEXT,
    avg_accel_ms2 TEXT,
    heading_deg TEXT,
    signal_state_num TEXT,
    incident_num TEXT,
    temp_c TEXT,
    visibility_km TEXT,
    rain_intensity_mmph TEXT,
    channel_busy_ratio_pct TEXT,
    msg_rate_hz TEXT,
    avg_comm_delay_ms TEXT,
    rssi_dbm TEXT,
    packet_loss_pct TEXT,
    speed_density_ratio TEXT,
    congestion_pressure TEXT,
    wireless_congestion_intensity TEXT,
    throughput_per_queued_vehicle TEXT,
    acceleration_directionality TEXT,
    weather_factor TEXT,
    label TEXT,
    _ingested_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- Staging 2: Daily Weather History
CREATE TABLE IF NOT EXISTS staging.stg_daily_weather (
    city TEXT,
    date TEXT,
    temperature_2m_max TEXT,
    temperature_2m_min TEXT,
    apparent_temperature_max TEXT,
    apparent_temperature_min TEXT,
    precipitation_sum TEXT,
    rain_sum TEXT,
    weather_code TEXT,
    wind_speed_10m_max TEXT,
    wind_gusts_10m_max TEXT,
    wind_direction_10m_dominant TEXT,
    _ingested_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- Staging 3: Indian Roads & Accidents
CREATE TABLE IF NOT EXISTS staging.stg_accidents_roads (
    accident_id TEXT,
    city TEXT,
    state TEXT,
    latitude TEXT,
    longitude TEXT,
    date TEXT,
    time TEXT,
    hour TEXT,
    day_of_week TEXT,
    is_weekend TEXT,
    road_type TEXT,
    lanes TEXT,
    traffic_signal TEXT,
    weather TEXT,
    visibility TEXT,
    temperature TEXT,
    traffic_density TEXT,
    cause TEXT,
    accident_severity TEXT,
    vehicles_involved TEXT,
    casualties TEXT,
    is_peak_hour TEXT,
    festival TEXT,
    risk_score TEXT,
    _ingested_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- Staging 4: PMC Hospital Infrastructure
CREATE TABLE IF NOT EXISTS staging.stg_hospital_infrastructure (
    city_name TEXT,
    zone_name TEXT,
    ward_name TEXT,
    zone_no TEXT,
    ward_no TEXT,
    facility_name TEXT,
    facility_type TEXT,
    class_type TEXT,
    pharmacy_available TEXT,
    emergency_beds TEXT,
    total_beds TEXT,
    doctor_count TEXT,
    nurse_count TEXT,
    midwife_count TEXT,
    avg_monthly_footfall TEXT,
    ambulance_service_available TEXT,
    ambulance_count TEXT,
    _ingested_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- Staging 5: Emergency EMS Dispatches
CREATE TABLE IF NOT EXISTS staging.stg_ems_events (
    event_id TEXT,
    timestamp TEXT,
    condition TEXT,
    chief_complaint TEXT,
    age TEXT,
    gender TEXT,
    sbp TEXT,
    heart_rate TEXT,
    spo2 TEXT,
    gcs TEXT,
    triage_priority TEXT,
    hospital_type TEXT,
    hospital_id TEXT,
    _ingested_at TIMESTAMPTZ DEFAULT clock_timestamp()
);
