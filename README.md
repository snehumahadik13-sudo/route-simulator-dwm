# Emergency Route Intelligence Warehouse (DWM Project)

A production-grade Data Warehousing and Data Mining (DWM) architecture integrating multimodal urban datasets (Traffic Telemetry, Meteorology, Road Accidents, Municipal Hospitals, and EMS Dispatches) into a PostgreSQL / Cloud Supabase analytical star schema.

---

## 1. Project Overview & Architecture

The objective of the **Emergency Route Intelligence Warehouse** is to support rapid ambulance route optimization, dispatch triage analysis, and road hazard risk mitigation.

```
+-----------------------------------------------------------------------------------+
|                                  SOURCE DATASETS                                  |
| Traffic (VANET) | Weather | Road Accidents | Hospital Infra (PMC) | EMS Events    |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                        STAGE 1: EXTRACT & INGESTION                               |
|   - Binary Deduplication (skips redundant files)                                  |
|   - Raw Ingestion into `staging.stg_*` tables                                     |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                        STAGE 2: CLEANING & TRANSFORMATION                         |
|   - Clamping negative wait times, queue lengths, rain intensities (>= 0)          |
|   - Normalizing sensor occupancy (capped at 100%)                                 |
|   - Standardizing dates/times to conformed `YYYYMMDD` and `HHMM` integer keys     |
|   - Derivation: Clinical Urgency Score (Glasgow Coma Scale + SpO2 + SBP + HR)     |
|   - Strict Source-Grounded Mapping (Zero synthetic hospital names or road names)  |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                        STAGE 3: DIMENSIONAL STAR SCHEMA                           |
| Conformed Dimensions:                                                             |
|   - `warehouse.dim_date`                                                          |
|   - `warehouse.dim_time_of_day`                                                   |
|   - `warehouse.dim_location`                                                      |
|   - `warehouse.dim_hospital` (737 genuine PMC clinics + H001-H004 destination types)
|   - `warehouse.dim_road_segment` (Genuine S001-S500 segment identifiers)          |
|   - `warehouse.dim_weather_condition`                                             |
| Fact Tables:                                                                      |
|   - `warehouse.fact_ems_events` (20,000 emergency calls)                          |
|   - `warehouse.fact_road_accidents` (20,000 incident hazards)                     |
|   - `warehouse.fact_traffic_performance` (195,714 telemetry records)              |
|   - `warehouse.fact_daily_weather` (91,320 metropolitan weather days)             |
+-----------------------------------------------------------------------------------+
```

---

## 2. Source Dataset Inventory & Strict Mapping Rules

| Dataset Domain | Source CSV File | Record Count | File Size | Dimensional Role | Integrity Enforcement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Traffic Telemetry** | `vanet_traffic_data.csv` | 195,714 | ~34.8 MB | `fact_traffic_performance` & `dim_road_segment` | Segments `S001-S500` stored directly from source; no fake road names. |
| **Meteorology** | `india_2000_2024_daily_weather.csv` | 91,320 | ~5.57 MB | `fact_daily_weather` & `dim_weather_condition` | 10 Indian cities, continuous daily history 2000-2024. |
| **Road Accidents** | `indian_roads_dataset.csv` | 20,000 | ~2.56 MB | `fact_road_accidents` | Treated strictly as **Accident Events**; NOT as a road network master. |
| **Duplicate Roads** | `indian_roads_dataset (2).csv` | 20,000 | ~2.56 MB | **Deduplicated & Skipped** | Exact SHA-256 match to `indian_roads_dataset.csv`. |
| **Hospital Infra** | `PMC Hospital Infrastructure (1).csv`| 737 | ~85 KB | `dim_hospital` | All 737 municipal facilities preserved with genuine reported bed counts. |
| **Emergency / EMS** | `ems_events_20000.csv` | 20,000 | ~2.03 MB | `fact_ems_events` & `dim_hospital` | `H001-H004` destination types preserved; no fabricated hospital names/beds. |

---

## 3. Data Integrity & Field Categorization Audit

### A. Source-Derived Fields (100% Genuine from CSVs)
- **`dim_road_segment`**: `road_segment_id` (`S001` through `S500`).
- **`dim_hospital`**: 737 municipal facility names, types, public/private classes, bed counts, and ambulance counts from `PMC Hospital Infrastructure (1).csv`.
- **`fact_road_accidents`**: `accident_id`, `road_type`, `lanes`, `traffic_signal`, `weather`, `visibility`, `temperature_c`, `traffic_density`, `cause`, `accident_severity`, `vehicles_involved`, `casualties`, `risk_score`.
- **`fact_ems_events`**: `event_id`, `condition`, `chief_complaint`, `patient_age`, `patient_gender`, `sbp`, `heart_rate`, `spo2`, `gcs`, `triage_priority`, `hospital_type_requested`.
- **`fact_traffic_performance`**: All 27 continuous telemetry metrics (`avg_speed_kmph`, `density_veh_per_km`, `flow_veh_per_hr`, `comm_delay`, `congestion_pressure`, `wireless_intensity`, etc.).
- **`fact_daily_weather`**: All macro-meteorological values (max/min temperatures, precipitation, wind speeds, WMO codes).

### B. Derived Fields (Calculated Mathematically / Logically)
- **`date_key`**: Standard integer key format `YYYYMMDD` extracted from dates.
- **`time_key`**: Standard integer key format `HHMM` extracted from timestamps.
- **`clinical_urgency_score`**: Derived medical risk index (1.0 to 10.0) based on Glasgow Coma Scale ($\le 8$), SpO2 ($< 85\%$), blood pressure decompensation, and triage priority.
- **Sensor Clamping**: Negative simulation noise in wait times, queue lengths, rain intensity clamped to $\ge 0$; occupancy capped at $\le 100\%$.
- **`is_fatal`**: Boolean flag derived from `accident_severity = 'fatal'`.

### C. Removed Synthetic / Fabricated Fields (Strict Data Integrity Policy)
1. **No Invented Road Names**: `dim_road_segment.road_name`, `corridor_group`, `lanes`, `speed_limit_kmph` default to `NULL` because `vanet_traffic_data.csv` provides only the segment codes `S001` to `S500`. (If a `public.roads` table exists in Supabase, it can be safely linked).
2. **No Invented Hospital Capacities**: `H001` through `H004` are stored strictly with their source-reported `hospital_type` (`cardiac_center`, `stroke_center`, `level1_trauma_center`, `general_emergency`). Capacities and staff counts are stored as `NULL` to reflect that `ems_events_20000.csv` does not record capacity numbers.

---

## 4. Preservation of Existing Supabase Tables

- **Strict Schema Isolation**: The warehouse runs exclusively inside custom schemas `staging` and `warehouse`.
- **Public Schema Protection**: Existing tables in the `public` schema (such as `public.roads`, if present) are **never modified, dropped, truncated, or overwritten**.
- **Idempotency**: All DDL commands use `IF NOT EXISTS` and fact/dimension inserts use `ON CONFLICT DO NOTHING`.

---

## 5. Setup & Execution Instructions

### Prerequisites
- Python 3.10+ (Tested with Python 3.14)
- A Cloud Supabase project (or PostgreSQL 14+ instance)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Supabase Database Connection
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Insert your Supabase Connection URI:
   ```env
   SUPABASE_DB_URL=postgresql://postgres.[your-project-ref]:[your-password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```

### Step 3: Run Local In-Memory Dry Run (No DB Required)
To verify all file extractions, data transformations, sensor clamping, and clinical scoring without connecting to an external database:
```bash
python -m etl.run_pipeline --dry-run
```

### Step 4: Execute Full End-to-End Pipeline to Supabase
```bash
python -m etl.run_pipeline --all
```

---

## 6. Sample Analytical Queries for DWM Lab Reports

### Query 1: Hospital Emergency Triage Load
```sql
SELECT 
    hospital_code,
    facility_name,
    facility_type,
    ownership_class,
    total_beds,
    total_dispatches,
    red_priority_cases,
    avg_urgency_score
FROM warehouse.vw_emergency_hospital_readiness
ORDER BY total_dispatches DESC;
```

### Query 2: Road Congestion & Gridlock Incidents per Segment
```sql
SELECT 
    road_segment_id,
    segment_identifier,
    mean_speed_kmph,
    mean_wait_time_sec,
    mean_congestion_pressure,
    gridlock_events_count
FROM warehouse.vw_high_risk_route_corridors
ORDER BY gridlock_events_count DESC
LIMIT 10;
```

### Query 3: Weather Impact on Accident Fatalities
```sql
SELECT 
    weather_condition,
    visibility,
    total_accidents,
    total_casualties,
    fatal_accidents,
    avg_risk_score
FROM warehouse.vw_weather_accident_correlation
ORDER BY total_accidents DESC;
```
