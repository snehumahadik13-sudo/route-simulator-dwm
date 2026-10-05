import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

# -----------------------------------------------------------------------------
# General Cleaning Utilities
# -----------------------------------------------------------------------------
NULL_STRINGS = {"", "na", "null", "none", "nan", "n/a", "n.a.", "nil"}

def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return None if s.lower() in NULL_STRINGS else s

def clean_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    s = clean_str(val)
    if s is None:
        return default
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default

def clean_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    s = clean_str(val)
    if s is None:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default

def clean_bool(val: Any) -> Optional[bool]:
    s = clean_str(val)
    if s is None:
        return None
    if s.lower() in {"1", "true", "yes", "t", "y"}:
        return True
    if s.lower() in {"0", "false", "no", "f", "n"}:
        return False
    return None

def parse_date_key(date_str: str) -> int:
    """Parses date string ('2023-10-22' or '2025-09-29T04:54:49') to integer YYYYMMDD."""
    if not date_str:
        return 19000101
    dt_part = date_str.split("T")[0].split(" ")[0].strip()
    parts = dt_part.split("-")
    if len(parts) == 3:
        try:
            return int(f"{int(parts[0]):04d}{int(parts[1]):02d}{int(parts[2]):02d}")
        except ValueError:
            pass
    return 19000101

def parse_time_key(time_str: str) -> int:
    """Parses time string ('5:00', '13:00', or '2025-09-29T04:54:49') to integer HHMM."""
    if not time_str:
        return 0
    if "T" in time_str:
        time_part = time_str.split("T")[1].split(".")[0].strip()
    elif " " in time_str:
        time_part = time_str.split(" ")[1].strip()
    else:
        time_part = time_str.strip()
        
    parts = time_part.split(":")
    if len(parts) >= 2:
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            return hour * 100 + minute
        except ValueError:
            pass
    return 0

# -----------------------------------------------------------------------------
# Hospital Definitions (Strictly Source-Grounded)
# ems_events_20000.csv provides ONLY code and capability type.
# We do NOT invent hospital names, addresses, or bed counts.
# -----------------------------------------------------------------------------
EMS_HOSPITALS = {
    "H001": {
        "facility_name": "EMS Destination Facility (H001)",
        "facility_type": "cardiac_center",
        "ownership_class": None,
        "ward_name": None,
        "zone_no": None,
        "total_beds": None,
        "emergency_beds": None,
        "doctor_count": None,
        "nurse_count": None,
        "midwife_count": None,
        "avg_monthly_footfall": None,
        "has_ambulance_service": None,
        "ambulance_count": None,
        "pharmacy_available": None
    },
    "H002": {
        "facility_name": "EMS Destination Facility (H002)",
        "facility_type": "stroke_center",
        "ownership_class": None,
        "ward_name": None,
        "zone_no": None,
        "total_beds": None,
        "emergency_beds": None,
        "doctor_count": None,
        "nurse_count": None,
        "midwife_count": None,
        "avg_monthly_footfall": None,
        "has_ambulance_service": None,
        "ambulance_count": None,
        "pharmacy_available": None
    },
    "H003": {
        "facility_name": "EMS Destination Facility (H003)",
        "facility_type": "level1_trauma_center",
        "ownership_class": None,
        "ward_name": None,
        "zone_no": None,
        "total_beds": None,
        "emergency_beds": None,
        "doctor_count": None,
        "nurse_count": None,
        "midwife_count": None,
        "avg_monthly_footfall": None,
        "has_ambulance_service": None,
        "ambulance_count": None,
        "pharmacy_available": None
    },
    "H004": {
        "facility_name": "EMS Destination Facility (H004)",
        "facility_type": "general_emergency",
        "ownership_class": None,
        "ward_name": None,
        "zone_no": None,
        "total_beds": None,
        "emergency_beds": None,
        "doctor_count": None,
        "nurse_count": None,
        "midwife_count": None,
        "avg_monthly_footfall": None,
        "has_ambulance_service": None,
        "ambulance_count": None,
        "pharmacy_available": None
    }
}

# -----------------------------------------------------------------------------
# Road Segment Definitions (Strictly Source-Grounded)
# vanet_traffic_data.csv provides ONLY segment identifiers S001 through S500.
# We do NOT invent fictitious road names, corridor groups, or speed limits.
# -----------------------------------------------------------------------------
def get_segment_metadata(segment_id: str) -> Dict[str, Any]:
    """
    Returns source-grounded attributes for road segments S001 - S500.
    Non-source attributes default to None (SQL NULL).
    """
    return {
        "road_segment_id": segment_id,
        "road_name": None,
        "corridor_group": None,
        "road_type": None,
        "lanes": None,
        "has_traffic_signal": None,
        "speed_limit_kmph": None
    }

# -----------------------------------------------------------------------------
# Clinical Emergency Severity Calculation
# -----------------------------------------------------------------------------
def calculate_clinical_urgency(sbp: int, heart_rate: int, spo2: int, gcs: int, triage: str) -> float:
    """
    Computes a composite clinical urgency score (1.0 - 10.0) based on vital sign instability.
    Directly derived from Glasgow Coma Scale (GCS), SpO2, Systolic BP, and Heart Rate.
    """
    points = 1.0
    
    # Neurological impairment (GCS 3-15)
    if gcs <= 8:
        points += 3.5  # Severe neurological compromise
    elif gcs <= 12:
        points += 2.0  # Moderate confusion/impairment
        
    # Respiratory compromise (SpO2 %)
    if spo2 < 85:
        points += 3.0  # Critical hypoxia
    elif spo2 < 92:
        points += 1.5  # Moderate hypoxia
        
    # Hemodynamic instability (SBP mmHg)
    if sbp < 90 or sbp > 180:
        points += 2.0  # Severe hypotension or hypertensive crisis
    elif sbp < 100 or sbp > 160:
        points += 1.0
        
    # Cardiac rhythm (Heart Rate bpm)
    if heart_rate < 50 or heart_rate > 130:
        points += 1.5  # Extreme bradycardia / tachycardia
        
    # Triage multiplier for immediate life threats
    if triage.lower() == 'red':
        points *= 1.25
        
    return round(min(10.0, points), 2)

# -----------------------------------------------------------------------------
# Specific Record Transformers
# -----------------------------------------------------------------------------
def transform_traffic_row(row: Dict[str, str]) -> Dict[str, Any]:
    ts_str = row['timestamp']
    return {
        "date_key": parse_date_key(ts_str),
        "time_key": parse_time_key(ts_str),
        "road_segment_id": row['road_segment_id'],
        "telemetry_timestamp": ts_str,
        "avg_speed_kmph": max(0.0, float(row['avg_speed_kmph'])),
        "density_veh_per_km": max(0.0, float(row['density_veh_per_km'])),
        "avg_wait_time_s": max(0.0, float(row['avg_wait_time_s'])),  # Clamp negative noise
        "occupancy_pct": min(100.0, max(0.0, float(row['occupancy_pct']))), # Cap at 100%
        "flow_veh_per_hr": max(0.0, float(row['flow_veh_per_hr'])),
        "queue_length_veh": max(0.0, float(row['queue_length_veh'])), # Clamp negative noise
        "avg_accel_ms2": float(row['avg_accel_ms2']),
        "heading_deg": max(0.0, min(360.0, float(row['heading_deg']))),
        "signal_state_num": float(row['signal_state_num']),
        "incident_num": max(0.0, float(row['incident_num'])),          # Clamp negative noise
        "temp_c": float(row['temp_c']),
        "visibility_km": max(0.0, float(row['visibility_km'])),
        "rain_intensity_mmph": max(0.0, float(row['rain_intensity_mmph'])), # Clamp negative
        "channel_busy_ratio_pct": float(row['channel_busy_ratio_pct']),
        "msg_rate_hz": float(row['msg_rate_hz']),
        "avg_comm_delay_ms": float(row['avg_comm_delay_ms']),
        "rssi_dbm": float(row['rssi_dbm']),
        "packet_loss_pct": float(row['packet_loss_pct']),
        "speed_density_ratio": float(row['speed_density_ratio']),
        "congestion_pressure": max(0.0, float(row['congestion_pressure'])),
        "wireless_congestion_intensity": max(0.0, float(row['wireless_congestion_intensity'])),
        "throughput_per_queued_vehicle": max(0.0, float(row['throughput_per_queued_vehicle'])),
        "acceleration_directionality": float(row['acceleration_directionality']),
        "weather_factor": float(row['weather_factor']),
        "congestion_label": row['label']
    }

def transform_weather_row(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "city": row['city'].strip(),
        "calendar_date": row['date'].strip(),
        "date_key": parse_date_key(row['date']),
        "temperature_2m_max": float(row['temperature_2m_max']),
        "temperature_2m_min": float(row['temperature_2m_min']),
        "apparent_temperature_max": float(row['apparent_temperature_max']),
        "apparent_temperature_min": float(row['apparent_temperature_min']),
        "precipitation_sum_mm": max(0.0, float(row['precipitation_sum'])),
        "rain_sum_mm": max(0.0, float(row['rain_sum'])),
        "weather_code": int(float(row['weather_code'])),
        "wind_speed_10m_max_kmph": float(row['wind_speed_10m_max']),
        "wind_gusts_10m_max_kmph": float(row['wind_gusts_10m_max']),
        "wind_direction_dominant_deg": float(row['wind_direction_10m_dominant'])
    }

def transform_accident_row(row: Dict[str, str]) -> Dict[str, Any]:
    t_raw = row['time'].strip()
    if ":" in t_raw and len(t_raw.split(":")[0]) == 1:
        t_raw = f"0{t_raw}"
        
    date_val = row['date'].strip()
    return {
        "accident_id": int(row['accident_id']),
        "city": row['city'].strip(),
        "state": row['state'].strip(),
        "latitude": float(row['latitude']),
        "longitude": float(row['longitude']),
        "date_key": parse_date_key(date_val),
        "time_key": parse_time_key(t_raw),
        "road_type": row['road_type'].strip(),
        "lanes": int(float(row['lanes'])),
        "traffic_signal": bool(clean_bool(row['traffic_signal'])),
        "weather": row['weather'].strip(),
        "visibility": row['visibility'].strip(),
        "temperature_c": float(row['temperature']),
        "traffic_density": row['traffic_density'].strip(),
        "cause": row['cause'].strip(),
        "accident_severity": row['accident_severity'].strip(),
        "vehicles_involved": int(float(row['vehicles_involved'])),
        "casualties": int(float(row['casualties'])),
        "is_peak_hour": bool(clean_bool(row['is_peak_hour'])),
        "festival": clean_str(row.get('festival')),
        "risk_score": float(row['risk_score'])
    }

def transform_ems_row(row: Dict[str, str]) -> Dict[str, Any]:
    ts_str = row['timestamp'].strip()
    sbp = int(row['sbp'])
    hr = int(row['heart_rate'])
    spo2 = int(row['spo2'])
    gcs = int(row['gcs'])
    priority = row['triage_priority'].strip()
    
    return {
        "event_id": row['event_id'].strip(),
        "date_key": parse_date_key(ts_str),
        "time_key": parse_time_key(ts_str),
        "hospital_id": row['hospital_id'].strip(),
        "condition": row['condition'].strip(),
        "chief_complaint": row['chief_complaint'].strip(),
        "patient_age": int(row['age']),
        "patient_gender": row['gender'].strip().lower(),
        "sbp": sbp,
        "heart_rate": hr,
        "spo2": spo2,
        "gcs": gcs,
        "triage_priority": priority,
        "hospital_type_requested": row['hospital_type'].strip(),
        "clinical_urgency_score": calculate_clinical_urgency(sbp, hr, spo2, gcs, priority)
    }

def transform_pmc_hospital_row(row: Dict[str, str]) -> Dict[str, Any]:
    zone_no = clean_int(row.get('Zone No.'))
    zone_name = clean_str(row.get('Zone Name'))
    
    return {
        "city_name": "Pune",
        "zone_no": zone_no,
        "zone_name": zone_name,
        "ward_name": clean_str(row.get('Ward Name')),
        "facility_name": row.get('Facility Name', '').strip(),
        "facility_type": clean_str(row.get('Type  (Hospital / Nursing Home / Lab)', 'General')),
        "ownership_class": "Private" if "priv" in row.get(' Class : (Public / Private)', '').lower() else "Public",
        "pharmacy_available": clean_bool(row.get('Pharmacy Available : Yes/No')),
        "emergency_beds": clean_int(row.get('Number of Beds in Emergency Wards ')),
        "total_beds": clean_int(row.get('Number of Beds in facility type')),
        "doctor_count": clean_int(row.get('Number of Doctors / Physicians')),
        "nurse_count": clean_int(row.get('Number of Nurses')),
        "midwife_count": clean_int(row.get('Number of Midwives Professional ')),
        "avg_monthly_footfall": clean_int(row.get('Average Monthly Patient Footfall')),
        "has_ambulance_service": clean_bool(row.get('Ambulance Service Available')),
        "ambulance_count": clean_int(row.get('Count of Ambulance'))
    }
