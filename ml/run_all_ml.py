"""
ml/run_all_ml.py
Orchestrates all ML modules and saves results to ml_results/.
"""
import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def main():
    print("\n" + "█"*65)
    print("  EMERGENCY ROUTE INTELLIGENCE — ML ANALYSIS SUITE")
    print("█"*65)

    all_results = {}
    errors = []

    # 1. Association Rules
    try:
        print("\n[1/5] Running Association Rule Mining...")
        from ml.association_rules import run_apriori
        all_results["association_rules"] = run_apriori()
    except Exception as e:
        print(f"  ERROR in association rules: {e}")
        errors.append(f"association_rules: {e}")

    # 2. K-Means Clustering
    try:
        print("\n[2/5] Running K-Means Clustering...")
        from ml.clustering import run_kmeans
        all_results["clustering"] = run_kmeans(n_clusters=4)
    except Exception as e:
        print(f"  ERROR in clustering: {e}")
        errors.append(f"clustering: {e}")

    # 3. Anomaly Detection
    try:
        print("\n[3/5] Running Anomaly Detection...")
        from ml.anomaly_detection import run_anomaly_detection
        all_results["anomaly_detection"] = run_anomaly_detection()
    except Exception as e:
        print(f"  ERROR in anomaly detection: {e}")
        errors.append(f"anomaly_detection: {e}")

    # 4. Classification
    try:
        print("\n[4/5] Running Severity Classification...")
        from ml.classification import run_classification
        all_results["classification"] = run_classification()
    except Exception as e:
        print(f"  ERROR in classification: {e}")
        errors.append(f"classification: {e}")

    # 5. Trend Analysis
    try:
        print("\n[5/5] Running Trend Analysis...")
        from ml.trend_analysis import run_trend_analysis
        all_results["trend_analysis"] = run_trend_analysis()
    except Exception as e:
        print(f"  ERROR in trend analysis: {e}")
        errors.append(f"trend_analysis: {e}")

    # 6. Random Forest — Delay Risk Classification (traffic telemetry)
    #    Distinct from step 4 (classification.py = accident_severity)
    try:
        print("\n[6/6] Running Random Forest Delay Risk Classification...")
        print("  (Target: delay_risk DERIVED from congestion_label / wait_time)")
        from ml.random_forest_delay import run_random_forest_delay
        all_results["random_forest_delay"] = run_random_forest_delay()
    except Exception as e:
        print(f"  ERROR in random_forest_delay: {e}")
        errors.append(f"random_forest_delay: {e}")

    # Final summary
    print("\n" + "="*65)
    print("ML SUITE COMPLETE")
    print("="*65)
    completed = [k for k in all_results if all_results[k]]
    print(f"  Completed: {', '.join(completed) if completed else 'None'}")
    if errors:
        print(f"  Errors:    {len(errors)}")
        for e in errors:
            print(f"    - {e}")
    print(f"\n  Results directory: {OUTPUT_DIR}")
    print("  Files:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        print(f"    {f.name}")

    # Save master summary
    summary_path = OUTPUT_DIR / "ml_summary.json"
    with open(summary_path, "w") as f:
        json.dump({"completed": completed, "errors": errors}, f, indent=2, default=str)
    return all_results


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
