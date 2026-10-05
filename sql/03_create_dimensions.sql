-- =============================================================================
-- Emergency Route Intelligence Warehouse (DWM Project)
-- Script 03: Conformed Dimension Tables (Strict Data Integrity Version)
-- Database Target: PostgreSQL / Cloud Supabase
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Dim_Date (Conformed Calendar Dimension)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key INT PRIMARY KEY,               -- Format: YYYYMMDD (e.g. 20250929)
    calendar_date DATE UNIQUE NOT NULL,
    year SMALLINT NOT NULL,
    quarter SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    month_name VARCHAR(15) NOT NULL,
    day SMALLINT NOT NULL,
    day_of_week VARCHAR(15) NOT NULL,
    day_of_week_num SMALLINT NOT NULL,      -- 1=Monday, 7=Sunday
    is_weekend BOOLEAN NOT NULL,
    festival VARCHAR(50)                    -- Real values from source: 'Holi', 'Eid', 'Diwali', 'New Year', or NULL
);

CREATE INDEX IF NOT EXISTS idx_dim_date_date ON warehouse.dim_date (calendar_date);
CREATE INDEX IF NOT EXISTS idx_dim_date_year_month ON warehouse.dim_date (year, month);

-- -----------------------------------------------------------------------------
-- 2. Dim_Time_Of_Day (Conformed Time Dimension)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_time_of_day (
    time_key INT PRIMARY KEY,               -- Format: HHMM (e.g. 1430 for 14:30)
    time_value TIME UNIQUE NOT NULL,
    hour_24 SMALLINT NOT NULL,              -- 0 - 23
    minute SMALLINT NOT NULL,               -- 0 - 59
    time_of_day_bucket VARCHAR(25) NOT NULL,-- 'Night', 'Morning Rush', 'Midday', 'Evening Rush', 'Late Evening'
    is_peak_hour BOOLEAN NOT NULL           -- Standardized traffic & incident peak flag
);

CREATE INDEX IF NOT EXISTS idx_dim_time_hour ON warehouse.dim_time_of_day (hour_24);

-- -----------------------------------------------------------------------------
-- 3. Dim_Location (Conformed Spatial & Administrative Dimension)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_location (
    location_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city VARCHAR(50) NOT NULL,
    state VARCHAR(50) NOT NULL,
    zone_no SMALLINT,
    zone_name VARCHAR(100),
    ward_name VARCHAR(100),
    latitude NUMERIC(9,6),
    longitude NUMERIC(9,6),
    is_metro_city BOOLEAN DEFAULT TRUE,
    CONSTRAINT uq_dim_location_point UNIQUE (city, state, zone_no, ward_name, latitude, longitude)
);

CREATE INDEX IF NOT EXISTS idx_dim_loc_city ON warehouse.dim_location (city);
CREATE INDEX IF NOT EXISTS idx_dim_loc_coords ON warehouse.dim_location (latitude, longitude);

-- -----------------------------------------------------------------------------
-- 4. Dim_Hospital (Hospital Infrastructure & Capabilities Dimension)
-- Strictly source-grounded: Real PMC facilities + source-reported EMS destination centers
-- No fabricated hospital names, bed counts, or ambulance counts.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_hospital (
    hospital_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hospital_code VARCHAR(20) UNIQUE,       -- 'H001'-'H004' (from EMS) or 'PMC-xxxx' (from PMC Infra)
    facility_name VARCHAR(255) NOT NULL,    -- Genuine PMC facility name or 'EMS Destination Facility (Hxxx)'
    facility_type VARCHAR(100) NOT NULL,    -- Source type: 'cardiac_center', 'stroke_center', 'MAT+GEN', etc.
    ownership_class VARCHAR(20),            -- 'Public', 'Private', or NULL
    ward_name VARCHAR(100),                 -- Genuine ward name from PMC, or NULL
    zone_no SMALLINT,                       -- Genuine zone number from PMC, or NULL
    total_beds INT,                         -- Genuine reported bed count, or NULL if not recorded
    emergency_beds INT,                     -- Genuine reported emergency beds, or NULL if not recorded
    doctor_count INT,                       -- Genuine reported doctor count, or NULL if not recorded
    nurse_count INT,                        -- Genuine reported nurse count, or NULL if not recorded
    midwife_count INT,                      -- Genuine reported midwife count, or NULL if not recorded
    avg_monthly_footfall INT,               -- Genuine reported footfall, or NULL if not recorded
    has_ambulance_service BOOLEAN,          -- Genuine reported ambulance service flag, or NULL
    ambulance_count INT,                    -- Genuine reported ambulance count, or NULL
    pharmacy_available BOOLEAN              -- Genuine reported pharmacy flag, or NULL
);

CREATE INDEX IF NOT EXISTS idx_dim_hosp_type ON warehouse.dim_hospital (facility_type);
CREATE INDEX IF NOT EXISTS idx_dim_hosp_code ON warehouse.dim_hospital (hospital_code);

-- -----------------------------------------------------------------------------
-- 5. Dim_Road_Segment (Network Telemetry Segments Dimension)
-- Strictly source-grounded: Stores genuine S001-S500 segment identifiers.
-- Non-source attributes (road_name, corridor_group, speed_limit) are NULL by default
-- to avoid inventing fictitious road infrastructure.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_road_segment (
    segment_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    road_segment_id VARCHAR(10) UNIQUE NOT NULL, -- 'S001' to 'S500' from vanet_traffic_data.csv
    road_name VARCHAR(100),                      -- NULL (no road names in source file)
    corridor_group VARCHAR(100),                 -- NULL (no corridor groupings in source file)
    road_type VARCHAR(20),                       -- NULL (not present in segment file)
    lanes SMALLINT,                              -- NULL (not present in segment file)
    has_traffic_signal BOOLEAN,                  -- NULL (not present in segment file)
    speed_limit_kmph SMALLINT                    -- NULL (not present in segment file)
);

CREATE INDEX IF NOT EXISTS idx_dim_road_segment_id ON warehouse.dim_road_segment (road_segment_id);

-- -----------------------------------------------------------------------------
-- 6. Dim_Weather_Condition (Meteorological Classification Dimension)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouse.dim_weather_condition (
    weather_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weather_code SMALLINT UNIQUE NOT NULL,       -- WMO weather code (0, 1, 2, 3, 51, 61, 65, etc.)
    condition_name VARCHAR(50) NOT NULL,         -- 'Clear Sky', 'Mainly Clear', 'Rain', 'Heavy Rain', etc.
    visibility_category VARCHAR(20) NOT NULL,    -- 'High (>8km)', 'Moderate (4-8km)', 'Low (<4km)'
    rain_category VARCHAR(20) NOT NULL           -- 'None', 'Light', 'Moderate', 'Heavy'
);
