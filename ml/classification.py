"""
ml/classification.py
Classifies accident delay-risk category using Random Forest.
Target: accident_severity (low/medium/high/fatal)
Uses proper train/test split and reports accuracy, precision, recall, F1.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_classification():
    print("\n" + "="*60)
    print("CLASSIFICATION — Accident Severity Prediction (Random Forest)")
    print("="*60)

    from ml.db_loader import load_accident_data
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    from sklearn.metrics import (
        classification_report, confusion_matrix,
        accuracy_score, f1_score
    )

    df = load_accident_data()
    print(f"Loaded {len(df):,} accident records.")

    if df.empty:
        print("No data available for classification.")
        return {}

    # ── Target variable ────────────────────────────────────────────────────
    target_col = "accident_severity" if "accident_severity" in df.columns else None
    if target_col is None:
        print("No accident_severity column found.")
        return {}

    df[target_col] = df[target_col].str.lower().str.strip()
    severity_counts = df[target_col].value_counts()
    print(f"\nTarget distribution:\n{severity_counts.to_string()}")

    # Remove classes with too few samples
    valid_classes = severity_counts[severity_counts >= 10].index
    df = df[df[target_col].isin(valid_classes)].copy()
    print(f"Using {len(df):,} records after filtering rare classes.")

    # ── Features ───────────────────────────────────────────────────────────
    le = LabelEncoder()
    feature_map = {}

    def encode_cat(series, name):
        if series.dtype == object:
            enc = LabelEncoder()
            return enc.fit_transform(series.fillna("unknown")), enc
        return series.fillna(0).values, None

    features = {}

    numeric_cols = ["temperature_c", "risk_score", "vehicles_involved", "casualties",
                    "lanes", "hour_24", "temperature"]
    for col in numeric_cols:
        if col in df.columns:
            features[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).values

    cat_cols = ["weather", "visibility", "road_type", "traffic_density", "cause"]
    encoders = {}
    for col in cat_cols:
        if col in df.columns:
            enc = LabelEncoder()
            features[col] = enc.fit_transform(df[col].fillna("unknown").astype(str))
            encoders[col] = enc

    bool_cols = ["traffic_signal", "is_peak_hour", "is_weekend"]
    for col in bool_cols:
        if col in df.columns:
            features[col] = df[col].fillna(False).astype(int).values

    if not features:
        print("Insufficient features for classification.")
        return {}

    X = np.column_stack(list(features.values()))
    feat_names = list(features.keys())

    y_raw = df[target_col].values
    le_target = LabelEncoder()
    y = le_target.fit_transform(y_raw)

    print(f"\nFeatures: {feat_names}")
    print(f"Classes:  {list(le_target.classes_)}")

    # ── Train/Test Split ───────────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\nTrain: {len(X_train):,}  Test: {len(X_test):,}")

    # ── Random Forest ──────────────────────────────────────────────────────
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=12, min_samples_leaf=5,
        random_state=42, n_jobs=-1, class_weight="balanced"
    )
    rf.fit(X_train, y_train)
    y_pred = rf.predict(X_test)

    acc = float(accuracy_score(y_test, y_pred))
    f1  = float(f1_score(y_test, y_pred, average="weighted"))

    print(f"\n{'─'*60}")
    print(f"RANDOM FOREST RESULTS:")
    print(f"  Accuracy:  {acc*100:.2f}%")
    print(f"  F1 Score (weighted): {f1:.4f}")
    print(f"\nClassification Report:")
    report_str = classification_report(y_test, y_pred, target_names=le_target.classes_)
    print(report_str)

    # Feature importances
    importances = sorted(
        zip(feat_names, rf.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    print("Top Feature Importances:")
    for name, imp in importances[:10]:
        bar = "█" * int(imp * 40)
        print(f"  {name:<25} {imp:.4f} {bar}")

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    cm_df = pd.DataFrame(cm, index=le_target.classes_, columns=le_target.classes_)
    print(f"\nConfusion Matrix:\n{cm_df.to_string()}")

    # ── Cross-validation ───────────────────────────────────────────────────
    cv_scores = cross_val_score(rf, X, y, cv=5, scoring="accuracy")
    print(f"\n5-Fold CV Accuracy: {cv_scores.mean()*100:.2f}% ± {cv_scores.std()*100:.2f}%")

    # ── Gradient Boosting (compare) ────────────────────────────────────────
    gb = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
    gb.fit(X_train, y_train)
    y_pred_gb = gb.predict(X_test)
    acc_gb = float(accuracy_score(y_test, y_pred_gb))
    f1_gb = float(f1_score(y_test, y_pred_gb, average="weighted"))
    print(f"\nGradient Boosting: Accuracy={acc_gb*100:.2f}%  F1={f1_gb:.4f}")

    # ── Save results ───────────────────────────────────────────────────────
    results = {
        "model": "RandomForestClassifier",
        "target": "accident_severity",
        "features": feat_names,
        "classes": list(le_target.classes_),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "accuracy": round(acc, 4),
        "f1_weighted": round(f1, 4),
        "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
        "cv_accuracy_std": round(float(cv_scores.std()), 4),
        "feature_importances": {n: round(float(i),4) for n,i in importances},
        "comparison_gb": {"accuracy": round(acc_gb,4), "f1": round(f1_gb,4)},
        "classification_report": report_str
    }

    with open(OUTPUT_DIR / "classification_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Classification results saved: {OUTPUT_DIR}/classification_results.json")
    return results


if __name__ == "__main__":
    run_classification()
