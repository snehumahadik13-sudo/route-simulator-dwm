"""
hospital_analysis.py
Hospital readiness analysis using source-reported PMC data and EMS dispatch data.
No fabricated capacities. Missing = NULL.
"""
import json
from pathlib import Path

import pandas as pd
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_hospital_analysis() -> dict:
    print("\n" + "="*65)
    print("HOSPITAL READINESS ANALYSIS")
    print("="*65)

    from ml.db_loader import query_df
    results = {}

    # ── 1. Hospital inventory from dim_hospital ────────────────────────────
    print("\n[1/3] Hospital Inventory...")
    try:
        df_hosp = query_df("""
            SELECT hospital_code, facility_name, facility_type, ownership_class,
                   ward_name, zone_no, total_beds, emergency_beds, doctor_count,
                   nurse_count, ambulance_count, pharmacy_available,
                   has_ambulance_service
            FROM warehouse.dim_hospital
            ORDER BY hospital_code
        """)
    except Exception:
        try:
            df_hosp = query_df("""
                SELECT city_name, zone_name, ward_name, zone_no, facility_name,
                       facility_type, class_type, pharmacy_available, emergency_beds,
                       total_beds, doctor_count, nurse_count, ambulance_count
                FROM staging.stg_hospital_infrastructure
            """)
        except Exception as e2:
            print(f"  Cannot load hospital data: {e2}")
            df_hosp = pd.DataFrame()

    if not df_hosp.empty:
        n_total = len(df_hosp)
        print(f"  Total facilities: {n_total:,}")

        if "ownership_class" in df_hosp.columns:
            ownership = df_hosp["ownership_class"].value_counts().to_dict()
            print(f"  Ownership: {ownership}")
            results["ownership_distribution"] = ownership
        elif "class_type" in df_hosp.columns:
            ownership = df_hosp["class_type"].value_counts().to_dict()
            print(f"  Ownership: {ownership}")
            results["ownership_distribution"] = ownership

        if "facility_type" in df_hosp.columns:
            ftype = df_hosp["facility_type"].value_counts().to_dict()
            print(f"  Facility types (top 10): {dict(list(ftype.items())[:10])}")
            results["facility_types"] = ftype

        # Bed statistics
        for bed_col in ["total_beds", "emergency_beds"]:
            if bed_col in df_hosp.columns:
                numeric_beds = pd.to_numeric(df_hosp[bed_col], errors="coerce")
                known = numeric_beds.dropna()
                if not known.empty:
                    stats = {
                        "total": int(known.sum()),
                        "mean": round(float(known.mean()), 1),
                        "max": int(known.max()),
                        "facilities_reporting": int(len(known)),
                        "facilities_unknown": int(len(df_hosp) - len(known))
                    }
                    print(f"  {bed_col}: {stats}")
                    results[f"{bed_col}_stats"] = stats

        if "ambulance_count" in df_hosp.columns:
            amb = pd.to_numeric(df_hosp["ambulance_count"], errors="coerce")
            amb_known = amb.dropna()
            if not amb_known.empty:
                results["ambulance_stats"] = {
                    "total_ambulances": int(amb_known.sum()),
                    "max_at_facility": int(amb_known.max()),
                    "facilities_with_ambulance": int((amb_known > 0).sum())
                }
                print(f"  Ambulances: {results['ambulance_stats']}")

        results["total_facilities"] = n_total
        df_hosp.to_csv(OUTPUT_DIR / "hospital_inventory.csv", index=False)

    # ── 2. EMS Dispatch Load per Hospital ─────────────────────────────────
    print("\n[2/3] EMS Dispatch Load per Hospital...")
    try:
        df_dispatch = query_df("""
            SELECT h.hospital_code, h.facility_type,
                   COUNT(e.ems_fact_key) as total_dispatches,
                   SUM(CASE WHEN e.triage_priority='red' THEN 1 ELSE 0 END) as red_cases,
                   SUM(CASE WHEN e.triage_priority='yellow' THEN 1 ELSE 0 END) as yellow_cases,
                   ROUND(AVG(e.clinical_urgency_score)::numeric, 3) as avg_urgency,
                   ROUND(AVG(e.patient_age)::numeric, 1) as avg_patient_age
            FROM warehouse.dim_hospital h
            LEFT JOIN warehouse.fact_ems_events e ON h.hospital_key = e.hospital_key
            WHERE h.hospital_code IN ('H001','H002','H003','H004')
            GROUP BY h.hospital_code, h.facility_type
            ORDER BY total_dispatches DESC
        """)
        if not df_dispatch.empty:
            print(f"  EMS destination load:")
            for _, row in df_dispatch.iterrows():
                print(f"    {row['hospital_code']} ({row['facility_type']}): "
                      f"{int(row['total_dispatches']):,} dispatches, "
                      f"avg urgency={row['avg_urgency']}, "
                      f"red={int(row['red_cases'])}")
            results["ems_dispatch_load"] = df_dispatch.to_dict(orient="records")
            df_dispatch.to_csv(OUTPUT_DIR / "hospital_ems_load.csv", index=False)
    except Exception as e:
        print(f"  EMS dispatch query failed: {e}")
        # Try staging
        try:
            df_stg = query_df("""
                SELECT hospital_id, hospital_type,
                       COUNT(*) as dispatch_count,
                       SUM(CASE WHEN triage_priority='red' THEN 1 ELSE 0 END) as red_count
                FROM staging.stg_ems_events
                GROUP BY hospital_id, hospital_type
                ORDER BY dispatch_count DESC
            """)
            if not df_stg.empty:
                print(f"  EMS by hospital_id (staging):")
                for _, row in df_stg.iterrows():
                    print(f"    {row['hospital_id']} ({row['hospital_type']}): {int(row['dispatch_count']):,}")
                results["ems_dispatch_load"] = df_stg.to_dict(orient="records")
        except Exception as e2:
            print(f"  Staging fallback also failed: {e2}")

    # ── 3. Readiness View ─────────────────────────────────────────────────
    print("\n[3/3] Readiness Assessment...")
    try:
        df_ready = query_df("""
            SELECT hospital_code, facility_name, facility_type, ownership_class,
                   total_beds, emergency_beds, ambulance_count,
                   total_dispatches, red_priority_cases, avg_urgency_score
            FROM warehouse.vw_emergency_hospital_readiness
            ORDER BY total_dispatches DESC NULLS LAST
        """)
        if not df_ready.empty:
            print(f"  Readiness view returned {len(df_ready)} records.")
            df_ready.to_csv(OUTPUT_DIR / "hospital_readiness.csv", index=False)
            results["readiness_data"] = df_ready.to_dict(orient="records")
    except Exception as e:
        print(f"  Readiness view not yet available: {e}")

    with open(OUTPUT_DIR / "hospital_analysis.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✓ Hospital analysis saved: {OUTPUT_DIR}/hospital_analysis.json")
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    run_hospital_analysis()
