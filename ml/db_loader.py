"""
ml/db_loader.py — Fetches data from warehouse/staging for ML modules.
Uses psycopg with pandas for efficient analytical queries.
"""
import os
import sys
from pathlib import Path
import pandas as pd

def load_env(path=None):
    if path is None:
        path = Path(__file__).resolve().parent.parent / ".env"
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def get_db_url():
    env = load_env()
    url = env.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL not found in .env")
    return url

def query_df(sql: str, params=None) -> pd.DataFrame:
    """Execute SQL and return a pandas DataFrame."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("pip install 'psycopg[binary]'")
    url = get_db_url()
    conn = psycopg.connect(url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    finally:
        conn.close()


def load_traffic_data(limit=None) -> pd.DataFrame:
    """Load VANET traffic telemetry from warehouse or public schema."""
    lim = f"LIMIT {limit}" if limit else ""
    # Try warehouse first, fall back to public
    try:
        df = query_df(f"""
            SELECT
                t.segment_key, s.road_segment_id,
                t.avg_speed_kmph, t.density_veh_per_km,
                t.avg_wait_time_s, t.occupancy_pct,
                t.flow_veh_per_hr, t.queue_length_veh,
                t.congestion_pressure, t.incident_num,
                t.temp_c, t.visibility_km, t.rain_intensity_mmph,
                t.congestion_label, t.date_key,
                d.hour_24, d2.is_weekend
            FROM warehouse.fact_traffic_performance t
            JOIN warehouse.dim_road_segment s ON t.segment_key = s.segment_key
            JOIN warehouse.dim_time_of_day d ON t.time_key = d.time_key
            JOIN warehouse.dim_date d2 ON t.date_key = d2.date_key
            {lim}
        """)
        if not df.empty:
            return df
    except Exception:
        pass
    # Fall back to public.traffic
    try:
        df = query_df(f"""
            SELECT
                road_segment_id,
                avg_speed_kmph::float, density_veh_per_km::float,
                avg_wait_time_s::float, occupancy_pct::float,
                flow_veh_per_hr::float, queue_length_veh::float,
                congestion_pressure::float, incident_num::float,
                temp_c::float, visibility_km::float,
                rain_intensity_mmph::float, label as congestion_label
            FROM public.traffic
            {lim}
        """)
        return df
    except Exception as e:
        raise RuntimeError(f"Cannot load traffic data: {e}")


def load_accident_data() -> pd.DataFrame:
    """Load accident facts from warehouse or public schema."""
    try:
        df = query_df("""
            SELECT
                a.accident_fact_key, a.date_key,
                l.city, l.state,
                a.road_type, a.lanes, a.traffic_signal,
                a.weather, a.visibility, a.temperature_c,
                a.traffic_density, a.cause,
                a.accident_severity, a.vehicles_involved,
                a.casualties, a.is_peak_hour, a.risk_score,
                a.is_fatal, t.hour_24
            FROM warehouse.fact_road_accidents a
            JOIN warehouse.dim_location l ON a.location_key = l.location_key
            JOIN warehouse.dim_time_of_day t ON a.time_key = t.time_key
        """)
        if not df.empty:
            return df
    except Exception:
        pass
    return query_df("""
        SELECT
            accident_id, city, state, latitude::float, longitude::float,
            date, hour::int, day_of_week, is_weekend::bool,
            road_type, lanes::int, traffic_signal::bool,
            weather, visibility, temperature::float, traffic_density,
            cause, accident_severity, vehicles_involved::int,
            casualties::int, is_peak_hour::bool, risk_score::float
        FROM public.accidents
    """)


def load_ems_data() -> pd.DataFrame:
    """Load EMS event facts."""
    try:
        df = query_df("""
            SELECT
                e.event_id, e.date_key,
                h.hospital_code, h.facility_type,
                e.condition, e.chief_complaint,
                e.patient_age, e.patient_gender,
                e.sbp, e.heart_rate, e.spo2, e.gcs,
                e.triage_priority, e.clinical_urgency_score,
                t.hour_24, t.time_of_day_bucket, t.is_peak_hour
            FROM warehouse.fact_ems_events e
            JOIN warehouse.dim_hospital h ON e.hospital_key = h.hospital_key
            JOIN warehouse.dim_time_of_day t ON e.time_key = t.time_key
        """)
        if not df.empty:
            return df
    except Exception:
        pass
    return query_df("""
        SELECT event_id, timestamp, condition, chief_complaint,
               age::int, gender, sbp::int, heart_rate::int,
               spo2::int, gcs::int, triage_priority, hospital_type, hospital_id
        FROM staging.stg_ems_events
    """)


def load_weather_data() -> pd.DataFrame:
    """Load daily weather facts."""
    try:
        df = query_df("""
            SELECT city, calendar_date, temperature_2m_max,
                   temperature_2m_min, precipitation_sum_mm,
                   rain_sum_mm, weather_code,
                   wind_speed_10m_max_kmph, wind_gusts_10m_max_kmph,
                   wind_direction_dominant_deg
            FROM warehouse.fact_daily_weather
        """)
        if not df.empty:
            return df
    except Exception:
        pass
    return query_df("""
        SELECT city, date, temperature_2m_max::float, temperature_2m_min::float,
               precipitation_sum::float, rain_sum::float, weather_code::int,
               wind_speed_10m_max::float, wind_gusts_10m_max::float
        FROM public.dim_weather
    """)


def load_segment_stats() -> pd.DataFrame:
    """Aggregate traffic metrics per road segment."""
    try:
        df = query_df("""
            SELECT
                s.road_segment_id,
                AVG(t.avg_speed_kmph) as mean_speed,
                AVG(t.density_veh_per_km) as mean_density,
                AVG(t.avg_wait_time_s) as mean_wait,
                AVG(t.occupancy_pct) as mean_occupancy,
                AVG(t.congestion_pressure) as mean_congestion,
                AVG(t.incident_num) as mean_incidents,
                AVG(t.visibility_km) as mean_visibility,
                AVG(t.rain_intensity_mmph) as mean_rain,
                COUNT(*) as ping_count,
                SUM(CASE WHEN t.congestion_label='Gridlock' THEN 1 ELSE 0 END) as gridlock_count
            FROM warehouse.fact_traffic_performance t
            JOIN warehouse.dim_road_segment s ON t.segment_key=s.segment_key
            GROUP BY s.road_segment_id
            ORDER BY s.road_segment_id
        """)
        if not df.empty:
            return df
    except Exception:
        pass
    # From public.traffic
    return query_df("""
        SELECT
            road_segment_id,
            AVG(avg_speed_kmph::float) as mean_speed,
            AVG(density_veh_per_km::float) as mean_density,
            AVG(avg_wait_time_s::float) as mean_wait,
            AVG(occupancy_pct::float) as mean_occupancy,
            AVG(congestion_pressure::float) as mean_congestion,
            AVG(incident_num::float) as mean_incidents,
            AVG(visibility_km::float) as mean_visibility,
            AVG(rain_intensity_mmph::float) as mean_rain,
            COUNT(*) as ping_count,
            SUM(CASE WHEN label='Gridlock' THEN 1 ELSE 0 END) as gridlock_count
        FROM public.traffic
        GROUP BY road_segment_id
        ORDER BY road_segment_id
    """)
