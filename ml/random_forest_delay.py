"""
ml/random_forest_delay.py
=========================
Random Forest Classification — Emergency Route Delay Risk

TARGET:  delay_risk  (Low / Medium / High)
         DERIVED from VANET traffic telemetry:
           - congestion_label  (Gridlock/Heavy -> High, Moderate -> Medium,
                                Free-Flow/Light/Very-Light -> Low)
           - avg_wait_time_s fallback: >=90s -> High, >=40s -> Medium, else Low

FEATURES (source-derived from warehouse traffic facts + embedded weather):
  avg_speed_kmph, density_veh_per_km, avg_wait_time_s, occupancy_pct,
  flow_veh_per_hr, queue_length_veh, congestion_pressure, incident_num,
  temp_c, visibility_km, rain_intensity_mmph, hour_24, is_weekend

METHODOLOGY:
  - StandardScaler fit on TRAIN only (no data leakage)
  - 80/20 stratified train/test split (random_state=42)
  - RandomForestClassifier(n_estimators=200, max_depth=15,
                           class_weight='balanced', random_state=42)
  - 5-fold Stratified CV on training set
  - Reports: accuracy, precision, recall, F1 (weighted),
             confusion matrix, feature importances, per-class metrics
  - Saves trained model: ml_results/rf_delay_model.joblib
  - Saves results:       ml_results/rf_delay_results.json

DISTINCTION FROM classification.py:
  - classification.py -> target = accident_severity (injury/fatal/minor...)
  - this module       -> target = delay_risk        (Low/Medium/High traffic delay)
    Using traffic telemetry features, not accident records.

NOTE: All values computed from real warehouse/source data.
      This is an academic historical classification model.
      Do NOT use for real-time emergency dispatching.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)

# -- Congestion label -> delay risk mapping (SOURCE-DERIVED) ------------------
CONGESTION_TO_DELAY = {
    "Gridlock":    "High",
    "Heavy":       "High",
    "Moderate":    "Medium",
    "Light":       "Low",
    "Free-Flow":   "Low",
    "Very-Light":  "Low",
    "Very Light":  "Low",
    "Free Flow":   "Low",
}

WAIT_HIGH_S   = 90   # >= 90 s  -> High
WAIT_MEDIUM_S = 40   # >= 40 s  -> Medium


def _derive_delay_risk(df: pd.DataFrame) -> pd.Series:
    """
    Create delay_risk label from source columns.
    Priority: congestion_label > avg_wait_time_s > occupancy_pct.
    Returns pd.Series of 'Low' / 'Medium' / 'High'.
    Classification: DERIVED
    """
    label = pd.Series("", index=df.index, dtype=str)

    # 1. congestion_label column (most direct)
    if "congestion_label" in df.columns:
        mapped = df["congestion_label"].map(CONGESTION_TO_DELAY)
        valid  = mapped.notna()
        label[valid] = mapped[valid]

    # 2. avg_wait_time_s fallback for unlabelled rows
    if "avg_wait_time_s" in df.columns:
        wait    = pd.to_numeric(df["avg_wait_time_s"], errors="coerce").fillna(0)
        unknown = label == ""
        label.loc[unknown & (wait >= WAIT_HIGH_S)]                           = "High"
        label.loc[unknown & (wait >= WAIT_MEDIUM_S) & (wait < WAIT_HIGH_S)] = "Medium"
        label.loc[unknown & (wait < WAIT_MEDIUM_S)]                          = "Low"

    # 3. occupancy_pct last resort
    if "occupancy_pct" in df.columns:
        occ     = pd.to_numeric(df["occupancy_pct"], errors="coerce").fillna(0)
        unknown = label == ""
        label.loc[unknown & (occ >= 0.75)]                 = "High"
        label.loc[unknown & (occ >= 0.40) & (occ < 0.75)] = "Medium"
        label.loc[unknown & (occ < 0.40)]                  = "Low"

    label = label.replace("", "Medium")
    return label


def _save_json(obj: dict, filename: str) -> None:
    with open(OUTPUT_DIR / filename, "w") as fh:
        json.dump(obj, fh, indent=2)


def run_random_forest_delay(sample_limit: int = 60_000) -> dict:
    """
    Train and evaluate a Random Forest classifier for delay_risk.
    Returns results dict; also saves to ml_results/rf_delay_results.json.
    """
    print("\\n" + "=" * 65)
    print("RANDOM FOREST CLASSIFICATION -- Emergency Route Delay Risk")
    print("=" * 65)
    print("Target : delay_risk  (Low / Medium / High)  [DERIVED]")
    print("Distinct from classification.py (which targets accident_severity)")

    # -- Import ML libraries --------------------------------------------------
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import (
        train_test_split, cross_val_score, StratifiedKFold
    )
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.metrics import (
        accuracy_score, f1_score, precision_score, recall_score,
        classification_report, confusion_matrix,
    )

    _joblib_ok = False
    try:
        import joblib
        _joblib_ok = True
    except ImportError:
        print("  Warning: joblib not available -- model will not be persisted.")

    # -- Load traffic data ---------------------------------------------------
    from ml.db_loader import load_traffic_data
    print(f"\\nLoading VANET traffic telemetry (limit={sample_limit:,})...")
    df = load_traffic_data(limit=sample_limit)
    print(f"  -> {len(df):,} records loaded.")

    if df.empty:
        msg = "No traffic data available for Random Forest training."
        print(f"  X {msg}")
        result = {"error": msg}
        _save_json(result, "rf_delay_results.json")
        return result

    # -- Derive target -------------------------------------------------------
    df["delay_risk"] = _derive_delay_risk(df)
    dist = df["delay_risk"].value_counts()
    print(f"\\nDelay-risk distribution (DERIVED from congestion_label / wait_time):")
    print(dist.to_string())

    valid_classes = dist[dist >= 10].index.tolist()
    df = df[df["delay_risk"].isin(valid_classes)].copy()
    print(f"Records after filtering rare classes: {len(df):,}")

    if len(df) < 100:
        msg = "Insufficient records for classification after class filtering."
        print(f"  X {msg}")
        result = {"error": msg}
        _save_json(result, "rf_delay_results.json")
        return result

    # -- Feature selection ---------------------------------------------------
    numeric_candidates = [
        "avg_speed_kmph",
        "density_veh_per_km",
        "avg_wait_time_s",
        "occupancy_pct",
        "flow_veh_per_hr",
        "queue_length_veh",
        "congestion_pressure",
        "incident_num",
        "temp_c",
        "visibility_km",
        "rain_intensity_mmph",
    ]
    time_candidates = ["hour_24", "is_weekend"]

    feature_cols = [c for c in numeric_candidates if c in df.columns]
    feature_cols += [c for c in time_candidates if c in df.columns]

    if not feature_cols:
        msg = "No usable feature columns found in traffic data."
        print(f"  X {msg}")
        result = {"error": msg}
        _save_json(result, "rf_delay_results.json")
        return result

    print(f"\\nFeatures ({len(feature_cols)}): {feature_cols}")

    # -- Build X matrix -------------------------------------------------------
    X_raw = df[feature_cols].copy()
    for col in feature_cols:
        X_raw[col] = pd.to_numeric(X_raw[col], errors="coerce")

    col_medians = X_raw.median(numeric_only=True)
    X_raw = X_raw.fillna(col_medians)

    le = LabelEncoder()
    y  = le.fit_transform(df["delay_risk"])
    class_names = list(le.classes_)
    print(f"Encoded classes: {dict(enumerate(class_names))}")

    # -- Train/Test split -----------------------------------------------------
    X_train, X_test, y_train, y_test = train_test_split(
        X_raw.values, y,
        test_size=0.20,
        random_state=42,
        stratify=y,
    )
    print(f"\\nTrain: {len(X_train):,}   Test: {len(X_test):,}")

    # -- Scale -- fit ONLY on train -------------------------------------------
    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # -- Train RandomForest ---------------------------------------------------
    print("\\nTraining RandomForestClassifier(200 trees, max_depth=15)...")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=15,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
        class_weight="balanced",
    )
    rf.fit(X_train_s, y_train)
    y_pred = rf.predict(X_test_s)

    # -- Metrics -------------------------------------------------------------
    acc  = float(accuracy_score(y_test, y_pred))
    f1_w = float(f1_score(y_test, y_pred, average="weighted"))
    prec = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
    rec  = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))

    print(f"\\n{'--'*28}")
    print("RANDOM FOREST RESULTS -- Delay Risk Classification")
    print(f"  Accuracy  : {acc*100:.2f}%")
    print(f"  Precision : {prec:.4f} (weighted)")
    print(f"  Recall    : {rec:.4f}  (weighted)")
    print(f"  F1 Score  : {f1_w:.4f} (weighted)")

    report_str = classification_report(y_test, y_pred, target_names=class_names)
    print(f"\\nClassification Report:\\n{report_str}")

    # Per-class metrics
    pc_prec = precision_score(y_test, y_pred, average=None, zero_division=0)
    pc_rec  = recall_score(y_test, y_pred,    average=None, zero_division=0)
    pc_f1   = f1_score(y_test, y_pred,        average=None, zero_division=0)
    per_class = {}
    for i, cls in enumerate(class_names):
        per_class[cls] = {
            "precision": round(float(pc_prec[i]), 4),
            "recall":    round(float(pc_rec[i]),  4),
            "f1":        round(float(pc_f1[i]),   4),
            "support":   int(np.sum(y_test == i)),
        }

    # -- Confusion matrix ----------------------------------------------------
    cm = confusion_matrix(y_test, y_pred)
    print(f"\\nConfusion Matrix:")
    print(pd.DataFrame(cm, index=class_names, columns=class_names).to_string())

    # -- Feature importances -------------------------------------------------
    importances = sorted(
        zip(feature_cols, rf.feature_importances_),
        key=lambda x: x[1], reverse=True,
    )
    print("\\nTop Feature Importances:")
    for name, imp in importances:
        bar = "X" * int(imp * 50)
        print(f"  {name:<30} {imp:.4f}  {bar}")

    # -- 5-fold CV -----------------------------------------------------------
    print("\\n5-Fold Stratified CV (on training set)...")
    cv   = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cvsc = cross_val_score(rf, X_train_s, y_train, cv=cv, scoring="accuracy")
    print(f"  CV Accuracy: {cvsc.mean()*100:.2f}% +/- {cvsc.std()*100:.2f}%")

    # -- Save model (joblib) -------------------------------------------------
    if _joblib_ok:
        import joblib
        bundle = {
            "rf": rf, "scaler": scaler, "le": le,
            "feature_cols": feature_cols,
            "class_names": class_names,
            "col_medians": col_medians.to_dict(),
        }
        joblib.dump(bundle, OUTPUT_DIR / "rf_delay_model.joblib")
        print(f"\\nModel saved: {OUTPUT_DIR}/rf_delay_model.joblib")

    # -- Build result dict --------------------------------------------------
    results = {
        "model":   "RandomForestClassifier",
        "target":  "delay_risk",
        "target_type": "DERIVED",
        "target_derivation": (
            f"Derived from congestion_label (Gridlock/Heavy->High, "
            f"Moderate->Medium, Free-Flow/Light->Low) with "
            f"avg_wait_time_s fallback (>={WAIT_HIGH_S}s=High, "
            f">={WAIT_MEDIUM_S}s=Medium). Not ground-truth."
        ),
        "distinction": (
            "This model targets delay_risk from traffic telemetry. "
            "ml/classification.py targets accident_severity from accident records."
        ),
        "hyperparameters": {
            "n_estimators": 200, "max_depth": 15,
            "min_samples_leaf": 5, "class_weight": "balanced",
        },
        "features": feature_cols,
        "classes":  class_names,
        "train_size": int(len(X_train)),
        "test_size":  int(len(X_test)),
        "accuracy":           round(acc,  4),
        "precision_weighted": round(prec, 4),
        "recall_weighted":    round(rec,  4),
        "f1_weighted":        round(f1_w, 4),
        "cv_accuracy_mean":   round(float(cvsc.mean()), 4),
        "cv_accuracy_std":    round(float(cvsc.std()),  4),
        "feature_importances": {n: round(float(v), 5) for n, v in importances},
        "confusion_matrix": {
            "labels": class_names,
            "matrix": cm.tolist(),
        },
        "per_class_metrics": per_class,
        "classification_report": report_str,
        "note": (
            "Academic historical model. All metrics from real warehouse data. "
            "Do not use for real-time emergency dispatching."
        ),
    }

    _save_json(results, "rf_delay_results.json")
    print(f"Results saved: {OUTPUT_DIR}/rf_delay_results.json")
    return results


def predict_delay_risk(features: dict) -> dict:
    """
    Predict delay_risk for a single observation using the saved model.

    Parameters
    ----------
    features : dict
        Keys matching feature_cols used during training.
        Missing keys filled with training column medians.

    Returns
    -------
    dict with: predicted_class, probabilities, explanation,
               route_intelligence_note, input_features, note
    """
    try:
        import joblib
    except ImportError:
        return {"error": "joblib not installed -- cannot load saved model."}

    model_path = OUTPUT_DIR / "rf_delay_model.joblib"
    if not model_path.exists():
        return {
            "error": (
                "Model file not found. "
                "Run: python -m ml.run_all_ml  (or python -m ml.random_forest_delay)"
            )
        }

    bundle     = joblib.load(model_path)
    rf         = bundle["rf"]
    scaler     = bundle["scaler"]
    le         = bundle["le"]
    feat_cols  = bundle["feature_cols"]
    col_medians = bundle.get("col_medians", {})

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler, LabelEncoder

    row = []
    for f in feat_cols:
        val = features.get(f)
        if val is None or val == "":
            val = col_medians.get(f, 0)
        row.append(float(val))

    X   = np.array([row])
    X_s = scaler.transform(X)
    pred_idx   = rf.predict(X_s)[0]
    pred_class = le.inverse_transform([pred_idx])[0]
    proba      = rf.predict_proba(X_s)[0]
    proba_dict = {cls: round(float(p), 4) for cls, p in zip(le.classes_, proba)}

    # Top-3 driving features from importances
    imps = sorted(zip(feat_cols, rf.feature_importances_), key=lambda x: x[1], reverse=True)
    top3 = [n for n, _ in imps[:3]]
    exp_parts = [f"{f}={features.get(f, col_medians.get(f, 'N/A'))}" for f in top3]
    explanation = (
        f"Predicted '{pred_class}' delay risk. "
        f"Top drivers: {', '.join(exp_parts)}. "
        "RandomForest(200 trees, max_depth=15). "
        "Target 'delay_risk' is DERIVED -- academic model."
    )

    # Route Intelligence connection
    risk_to_score = {"Low": "0.0-0.35", "Medium": "0.35-0.65", "High": "0.65-1.0"}
    route_note = (
        f"A '{pred_class}' delay risk corresponds to a historical route "
        f"risk score in the range {risk_to_score.get(pred_class, '?')}. "
        "See Route Intelligence page for segment-level risk scores."
    )

    return {
        "predicted_class":         pred_class,
        "probabilities":           proba_dict,
        "explanation":             explanation,
        "route_intelligence_note": route_note,
        "model":  "RandomForestClassifier",
        "target": "delay_risk",
        "input_features": {f: features.get(f, col_medians.get(f, 0)) for f in feat_cols},
        "note": (
            "Academic historical prediction. "
            "delay_risk is DERIVED, not a ground-truth field."
        ),
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    run_random_forest_delay()
