-- =============================================================================
-- Emergency Route Intelligence Warehouse (DWM Project)
-- Script 04: Fact Tables (Business Process Metrics)
-- Database Target: PostgreSQL / Cloud Supabase
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Fact_Road_Accidents
-- Captures incident-level traffic collision and hazard risk events
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.fact_road_accidents (
    accident_fact_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    accident_id INT UNIQUE NOT NULL,
    date_key INT NOT NULL REFERENCES warehouse.dim_date(date_key),
    time_key INT NOT NULL REFERENCES warehouse.dim_time_of_day(time_key),
    location_key INT NOT NULL REFERENCES warehouse.dim_location(location_key),
    road_type VARCHAR(20) NOT NULL,
    lanes SMALLINT NOT NULL,
    traffic_signal BOOLEAN NOT NULL,
    weather VARCHAR(20) NOT NULL,
    visibility VARCHAR(20) NOT NULL,
    temperature_c NUMERIC(4,1) NOT NULL,
    traffic_density VARCHAR(20) NOT NULL,
    cause VARCHAR(50) NOT NULL,
    accident_severity VARCHAR(20) NOT NULL,
    vehicles_involved SMALLINT NOT NULL,
    casualties SMALLINT NOT NULL,
    is_peak_hour BOOLEAN NOT NULL,
    risk_score NUMERIC(3,2) NOT NULL,
    is_fatal BOOLEAN GENERATED ALWAYS AS (accident_severity = 'fatal') STORED
);

CREATE INDEX IF NOT EXISTS idx_fact_acc_date ON warehouse.fact_road_accidents(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_acc_loc ON warehouse.fact_road_accidents(location_key);
CREATE INDEX IF NOT EXISTS idx_fact_acc_severity ON warehouse.fact_road_accidents(accident_severity);
CREATE INDEX IF NOT EXISTS idx_fact_acc_risk ON warehouse.fact_road_accidents(risk_score);

-- -----------------------------------------------------------------------------
-- 2. Fact_EMS_Events
-- Captures patient emergency calls, clinical vitals, triage, and hospital assignment
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.fact_ems_events (
    ems_fact_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id VARCHAR(20) UNIQUE NOT NULL,
    date_key INT NOT NULL REFERENCES warehouse.dim_date(date_key),
    time_key INT NOT NULL REFERENCES warehouse.dim_time_of_day(time_key),
    hospital_key INT NOT NULL REFERENCES warehouse.dim_hospital(hospital_key),
    condition VARCHAR(30) NOT NULL,
    chief_complaint VARCHAR(100) NOT NULL,
    patient_age SMALLINT NOT NULL,
    patient_gender VARCHAR(10) NOT NULL,
    sbp SMALLINT NOT NULL,
    heart_rate SMALLINT NOT NULL,
    spo2 SMALLINT NOT NULL,
    gcs SMALLINT NOT NULL,
    triage_priority VARCHAR(10) NOT NULL,
    hospital_type_requested VARCHAR(50) NOT NULL,
    clinical_urgency_score NUMERIC(5,2) NOT NULL -- Derived composite vital instability index
);

CREATE INDEX IF NOT EXISTS idx_fact_ems_date ON warehouse.fact_ems_events(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_ems_hosp ON warehouse.fact_ems_events(hospital_key);
CREATE INDEX IF NOT EXISTS idx_fact_ems_priority ON warehouse.fact_ems_events(triage_priority);
CREATE INDEX IF NOT EXISTS idx_fact_ems_cond ON warehouse.fact_ems_events(condition);

-- -----------------------------------------------------------------------------
-- 3. Fact_Traffic_Performance
-- Captures microscopic VANET sensor telemetry and congestion pressure per road segment
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.fact_traffic_performance (
    traffic_fact_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_key INT NOT NULL REFERENCES warehouse.dim_date(date_key),
    time_key INT NOT NULL REFERENCES warehouse.dim_time_of_day(time_key),
    segment_key INT NOT NULL REFERENCES warehouse.dim_road_segment(segment_key),
    telemetry_timestamp TIMESTAMP NOT NULL,
    avg_speed_kmph NUMERIC(6,2) NOT NULL,
    density_veh_per_km NUMERIC(6,2) NOT NULL,
    avg_wait_time_s NUMERIC(6,2) NOT NULL,
    occupancy_pct NUMERIC(6,2) NOT NULL,
    flow_veh_per_hr NUMERIC(8,2) NOT NULL,
    queue_length_veh NUMERIC(6,2) NOT NULL,
    avg_accel_ms2 NUMERIC(6,3) NOT NULL,
    heading_deg NUMERIC(6,2) NOT NULL,
    signal_state_num NUMERIC(5,3) NOT NULL,
    incident_num NUMERIC(5,3) NOT NULL,
    temp_c NUMERIC(5,2) NOT NULL,
    visibility_km NUMERIC(5,2) NOT NULL,
    rain_intensity_mmph NUMERIC(5,2) NOT NULL,
    channel_busy_ratio_pct NUMERIC(5,2) NOT NULL,
    msg_rate_hz NUMERIC(5,2) NOT NULL,
    avg_comm_delay_ms NUMERIC(6,2) NOT NULL,
    rssi_dbm NUMERIC(6,2) NOT NULL,
    packet_loss_pct NUMERIC(5,2) NOT NULL,
    speed_density_ratio NUMERIC(8,4) NOT NULL,
    congestion_pressure NUMERIC(8,4) NOT NULL,
    wireless_congestion_intensity NUMERIC(8,4) NOT NULL,
    throughput_per_queued_vehicle NUMERIC(10,4) NOT NULL,
    acceleration_directionality NUMERIC(8,4) NOT NULL,
    weather_factor NUMERIC(8,4) NOT NULL,
    congestion_label VARCHAR(20) NOT NULL,
    CONSTRAINT uq_traffic_segment_timestamp UNIQUE (segment_key, telemetry_timestamp)
);

CREATE INDEX IF NOT EXISTS idx_fact_traffic_date ON warehouse.fact_traffic_performance(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_traffic_segment ON warehouse.fact_traffic_performance(segment_key);
CREATE INDEX IF NOT EXISTS idx_fact_traffic_label ON warehouse.fact_traffic_performance(congestion_label);
CREATE INDEX IF NOT EXISTS idx_fact_traffic_speed ON warehouse.fact_traffic_performance(avg_speed_kmph);

-- -----------------------------------------------------------------------------
-- 4. Fact_Daily_Weather
-- Captures macro meteorological conditions across Indian cities
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.fact_daily_weather (
    weather_fact_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_key INT NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key INT NOT NULL REFERENCES warehouse.dim_location(location_key),
    city VARCHAR(50) NOT NULL,
    calendar_date DATE NOT NULL,
    temperature_2m_max NUMERIC(5,2) NOT NULL,
    temperature_2m_min NUMERIC(5,2) NOT NULL,
    apparent_temperature_max NUMERIC(5,2) NOT NULL,
    apparent_temperature_min NUMERIC(5,2) NOT NULL,
    precipitation_sum_mm NUMERIC(6,2) NOT NULL,
    rain_sum_mm NUMERIC(6,2) NOT NULL,
    weather_code SMALLINT NOT NULL,
    wind_speed_10m_max_kmph NUMERIC(5,2) NOT NULL,
    wind_gusts_10m_max_kmph NUMERIC(5,2) NOT NULL,
    wind_direction_dominant_deg NUMERIC(5,1) NOT NULL,
    CONSTRAINT uq_weather_city_date UNIQUE (city, calendar_date)
);

CREATE INDEX IF NOT EXISTS idx_fact_weather_date ON warehouse.fact_daily_weather(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_weather_loc ON warehouse.fact_daily_weather(location_key);
