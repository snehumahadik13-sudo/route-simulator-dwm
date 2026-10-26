"""
ml/delay_regression.py
======================
Emergency Travel & Telemetry Delay Prediction — 3 Regression Models:
1. Random Forest Regressor
2. Decision Tree Regressor
3. XGBoost Regressor

TARGET:
  delay_minutes (actual intersection/corridor wait delay in minutes derived from avg_wait_time_s / 60.0)

FEATURES:
  avg_speed_kmph, density_veh_per_km, occupancy_pct, flow_veh_per_hr,
  queue_length_veh, congestion_pressure, incident_num, temp_c,
  visibility_km, rain_intensity_mmph, hour_24, is_weekend

METHODOLOGY:
  - Real warehouse traffic telemetry (fact_traffic_performance / vanet_traffic_data.csv)
  - 80/20 train/test split (random_state=42)
  - StandardScaler fit strictly on training set (no data leakage)
  - Evaluated on same test set: MAE, RMSE, R2, Accuracy within ±5 minutes
  - Automatic best model selection (lowest MAE, lowest RMSE, highest R2)
  - Model persistence for live browser delay predictions
"""
import os
import sys
import json
import warnings
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor

# Try native xgboost first, fallback to GradientBoostingRegressor
try:
    import xgboost as xgb
    from xgboost import XGBRegressor
    HAS_XGBOOST_NATIVE = True
except ImportError:
    from sklearn.ensemble import GradientBoostingRegressor
    HAS_XGBOOST_NATIVE = False

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)

MODEL_FILE = OUTPUT_DIR / "delay_regression_models.joblib"
RESULTS_FILE = OUTPUT_DIR / "delay_regression_results.json"

FEATURE_COLS = [
    "avg_speed_kmph",
    "density_veh_per_km",
    "occupancy_pct",
    "flow_veh_per_hr",
    "queue_length_veh",
    "congestion_pressure",
    "incident_num",
    "temp_c",
    "visibility_km",
    "rain_intensity_mmph",
    "hour_24",
    "is_weekend",
]

DEFAULT_MEDIANS = {
    "avg_speed_kmph": 45.0,
    "density_veh_per_km": 30.0,
    "occupancy_pct": 0.40,
    "flow_veh_per_hr": 850.0,
    "queue_length_veh": 3.5,
    "congestion_pressure": 0.40,
    "incident_num": 0.15,
    "temp_c": 28.0,
    "visibility_km": 8.0,
    "rain_intensity_mmph": 0.5,
    "hour_24": 14,
    "is_weekend": 0,
}

_CACHE_BUNDLE: Optional[Dict[str, Any]] = None


def load_raw_dataset(sample_limit: int = 50_000) -> pd.DataFrame:
    """Load real telemetry data from warehouse or fallback CSV."""
    df = pd.DataFrame()
    try:
        from ml.db_loader import load_traffic_data
        df = load_traffic_data(limit=sample_limit)
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        csv_file = BASE_DIR / "vanet_traffic_data.csv"
        if csv_file.exists():
            df = pd.read_csv(csv_file, nrows=sample_limit)
            if "wait_time_s" in df.columns and "avg_wait_time_s" not in df.columns:
                df["avg_wait_time_s"] = df["wait_time_s"]
            if "speed_kmph" in df.columns and "avg_speed_kmph" not in df.columns:
                df["avg_speed_kmph"] = df["speed_kmph"]
            if "hour" in df.columns and "hour_24" not in df.columns:
                df["hour_24"] = df["hour"]
            if "timestamp" in df.columns and "is_weekend" not in df.columns:
                try:
                    dt = pd.to_datetime(df["timestamp"], errors="coerce")
                    df["is_weekend"] = dt.dt.weekday.isin([5, 6]).astype(int)
                    if "hour_24" not in df.columns:
                        df["hour_24"] = dt.dt.hour.fillna(12).astype(int)
                except Exception:
                    df["is_weekend"] = 0

    if df.empty:
        raise RuntimeError("No traffic telemetry data available for ML delay regression.")

    return df


def train_and_evaluate_models(sample_limit: int = 50_000) -> Dict[str, Any]:
    """
    Train Random Forest, Decision Tree, and XGBoost Regressors on real data.
    Compute MAE, RMSE, R2, and Accuracy within ±5 minutes on the test set.
    Automatically select the best model.
    """
    global _CACHE_BUNDLE
    print(f"[ML Delay Regression] Loading dataset (sample_limit={sample_limit})...")
    df = load_raw_dataset(sample_limit=sample_limit)

    # ── Derive target: delay_minutes ──────────────────────────────────────────
    # avg_wait_time_s is the ground truth wait time from VANET telemetry in seconds
    if "avg_wait_time_s" not in df.columns:
        if "wait_time_s" in df.columns:
            df["avg_wait_time_s"] = df["wait_time_s"]
        else:
            raise RuntimeError("Required column 'avg_wait_time_s' missing for delay target.")

    df["avg_wait_time_s"] = pd.to_numeric(df["avg_wait_time_s"], errors="coerce")
    df = df.dropna(subset=["avg_wait_time_s"])
    df = df[df["avg_wait_time_s"] >= 0]

    # Target variable in minutes
    df["delay_minutes"] = df["avg_wait_time_s"] / 60.0

    # ── Feature matrix ────────────────────────────────────────────────────────
    for col in FEATURE_COLS:
        if col not in df.columns:
            df[col] = DEFAULT_MEDIANS.get(col, 0)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    col_medians = df[FEATURE_COLS].median(numeric_only=True).to_dict()
    for col in FEATURE_COLS:
        df[col] = df[col].fillna(col_medians.get(col, DEFAULT_MEDIANS.get(col, 0)))

    X = df[FEATURE_COLS].values
    y = df["delay_minutes"].values

    total_records = len(df)
    train_size = int(total_records * 0.8)
    test_size = total_records - train_size

    # ── Train / Test Split (80/20) ────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )

    # ── Preprocessing (fit strictly on train) ─────────────────────────────────
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    results_models = {}
    trained_models = {}

    # 1. Random Forest Regressor
    print("[ML Delay Regression] Training Random Forest Regressor...")
    rf = RandomForestRegressor(
        n_estimators=100,
        max_depth=12,
        min_samples_leaf=4,
        random_state=42,
        n_jobs=-1
    )
    rf.fit(X_train_s, y_train)
    rf_pred = rf.predict(X_test_s)
    rf_mae = float(mean_absolute_error(y_test, rf_pred))
    rf_rmse = float(np.sqrt(mean_squared_error(y_test, rf_pred)))
    rf_r2 = float(r2_score(y_test, rf_pred))
    rf_acc_5m = float(np.mean(np.abs(rf_pred - y_test) <= 5.0) * 100.0)
    rf_feat_imp = {col: round(float(imp), 4) for col, imp in zip(FEATURE_COLS, rf.feature_importances_)}

    results_models["Random Forest Regressor"] = {
        "model_key": "random_forest",
        "name": "Random Forest Regressor",
        "mae": round(rf_mae, 4),
        "rmse": round(rf_rmse, 4),
        "r2": round(rf_r2, 4),
        "accuracy_within_5_min": round(rf_acc_5m, 2),
        "feature_importances": rf_feat_imp,
    }
    trained_models["random_forest"] = rf

    # 2. Decision Tree Regressor
    print("[ML Delay Regression] Training Decision Tree Regressor...")
    dt = DecisionTreeRegressor(
        max_depth=8,
        min_samples_leaf=5,
        random_state=42
    )
    dt.fit(X_train_s, y_train)
    dt_pred = dt.predict(X_test_s)
    dt_mae = float(mean_absolute_error(y_test, dt_pred))
    dt_rmse = float(np.sqrt(mean_squared_error(y_test, dt_pred)))
    dt_r2 = float(r2_score(y_test, dt_pred))
    dt_acc_5m = float(np.mean(np.abs(dt_pred - y_test) <= 5.0) * 100.0)
    dt_feat_imp = {col: round(float(imp), 4) for col, imp in zip(FEATURE_COLS, dt.feature_importances_)}

    results_models["Decision Tree Regressor"] = {
        "model_key": "decision_tree",
        "name": "Decision Tree Regressor",
        "mae": round(dt_mae, 4),
        "rmse": round(dt_rmse, 4),
        "r2": round(dt_r2, 4),
        "accuracy_within_5_min": round(dt_acc_5m, 2),
        "feature_importances": dt_feat_imp,
    }
    trained_models["decision_tree"] = dt

    # 3. XGBoost Regressor
    print("[ML Delay Regression] Training XGBoost Regressor...")
    if HAS_XGBOOST_NATIVE:
        xgb_reg = XGBRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.08,
            random_state=42,
            n_jobs=-1
        )
    else:
        from sklearn.ensemble import GradientBoostingRegressor
        xgb_reg = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.08,
            random_state=42
        )

    xgb_reg.fit(X_train_s, y_train)
    xgb_pred = xgb_reg.predict(X_test_s)
    xgb_mae = float(mean_absolute_error(y_test, xgb_pred))
    xgb_rmse = float(np.sqrt(mean_squared_error(y_test, xgb_pred)))
    xgb_r2 = float(r2_score(y_test, xgb_pred))
    xgb_acc_5m = float(np.mean(np.abs(xgb_pred - y_test) <= 5.0) * 100.0)
    xgb_feat_imp = {col: round(float(imp), 4) for col, imp in zip(FEATURE_COLS, xgb_reg.feature_importances_)}

    results_models["XGBoost Regressor"] = {
        "model_key": "xgboost",
        "name": "XGBoost Regressor",
        "mae": round(xgb_mae, 4),
        "rmse": round(xgb_rmse, 4),
        "r2": round(xgb_r2, 4),
        "accuracy_within_5_min": round(xgb_acc_5m, 2),
        "feature_importances": xgb_feat_imp,
    }
    trained_models["xgboost"] = xgb_reg

    # ── Automatic Best Model Selection ────────────────────────────────────────
    # Ranking criteria: Lowest MAE, Lowest RMSE, Highest R2
    sorted_models = sorted(
        results_models.values(),
        key=lambda m: (m["mae"], m["rmse"], -m["r2"])
    )

    for rank_idx, m in enumerate(sorted_models, 1):
        m["rank"] = rank_idx

    best_model_info = sorted_models[0]
    best_model_name = best_model_info["name"]
    best_model_key = best_model_info["model_key"]

    summary = {
        "status": "success",
        "target_variable": "delay_minutes (Emergency Wait & Corridor Delay)",
        "training_records": len(X_train),
        "testing_records": len(X_test),
        "features": FEATURE_COLS,
        "feature_count": len(FEATURE_COLS),
        "col_medians": col_medians,
        "models": results_models,
        "comparison_table": sorted_models,
        "best_model": best_model_name,
        "best_model_key": best_model_key,
        "best_model_metrics": {
            "mae": best_model_info["mae"],
            "rmse": best_model_info["rmse"],
            "r2": best_model_info["r2"],
            "accuracy_within_5_min": best_model_info["accuracy_within_5_min"]
        },
        "selection_reason": (
            f"Based on actual test-set performance ({len(X_test):,} held-out samples), "
            f"{best_model_name} achieved the lowest MAE ({best_model_info['mae']:.4f} min) "
            f"and lowest RMSE ({best_model_info['rmse']:.4f} min) with an R² of {best_model_info['r2']:.4f}."
        )
    }

    # Save metrics JSON
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Save models & scaler bundle
    bundle = {
        "scaler": scaler,
        "models": trained_models,
        "summary": summary,
        "feature_cols": FEATURE_COLS,
        "col_medians": col_medians,
        "best_model_key": best_model_key,
        "best_model_name": best_model_name,
    }
    joblib.dump(bundle, MODEL_FILE)
    _CACHE_BUNDLE = bundle

    print(f"[ML Delay Regression] Complete. Best model: {best_model_name} (MAE={best_model_info['mae']})")
    return summary


def get_or_train_models() -> Dict[str, Any]:
    """Load cached model bundle or train if not present."""
    global _CACHE_BUNDLE
    if _CACHE_BUNDLE is not None:
        return _CACHE_BUNDLE

    if MODEL_FILE.exists() and RESULTS_FILE.exists():
        try:
            _CACHE_BUNDLE = joblib.load(MODEL_FILE)
            return _CACHE_BUNDLE
        except Exception:
            pass

    train_and_evaluate_models()
    return _CACHE_BUNDLE


def predict_delay_all_models(input_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run Delay Prediction across Random Forest, Decision Tree, and XGBoost Regressors.
    Returns individual predictions + automatically selected best model prediction.
    """
    bundle = get_or_train_models()
    scaler = bundle["scaler"]
    models = bundle["models"]
    summary = bundle.get("summary", {})
    feat_cols = bundle.get("feature_cols", FEATURE_COLS)
    col_medians = bundle.get("col_medians", DEFAULT_MEDIANS)
    best_key = bundle.get("best_model_key", "random_forest")
    best_name = bundle.get("best_model_name", "Random Forest Regressor")

    # Build numeric feature row
    row = []
    sanitized_inputs = {}
    for col in feat_cols:
        val = input_features.get(col)
        if val is None or val == "":
            val = col_medians.get(col, DEFAULT_MEDIANS.get(col, 0))
        try:
            val_float = float(val)
        except (ValueError, TypeError):
            val_float = float(col_medians.get(col, DEFAULT_MEDIANS.get(col, 0)))
        row.append(val_float)
        sanitized_inputs[col] = val_float

    X_in = np.array([row])
    X_scaled = scaler.transform(X_in)

    predictions = {}
    display_names = {
        "random_forest": "Random Forest Regressor",
        "decision_tree": "Decision Tree Regressor",
        "xgboost": "XGBoost Regressor",
    }

    for key, model_obj in models.items():
        pred_val = float(model_obj.predict(X_scaled)[0])
        pred_min = max(0.0, round(pred_val, 2))
        d_name = display_names.get(key, key.replace("_", " ").title())
        predictions[d_name] = {
            "model_key": key,
            "predicted_delay_minutes": pred_min,
            "predicted_delay_text": f"{pred_min:.2f} min"
        }

    best_pred_info = predictions.get(best_name) or predictions.get("Random Forest Regressor")
    best_pred_val = best_pred_info["predicted_delay_minutes"]

    return {
        "status": "success",
        "input_features": sanitized_inputs,
        "predictions": predictions,
        "best_model": best_name,
        "best_model_key": best_key,
        "best_model_predicted_delay": best_pred_val,
        "best_model_predicted_delay_text": f"{best_pred_val:.2f} minutes",
        "metrics_summary": summary.get("models", {}),
        "reason": (
            f"Based on actual test-set performance, {best_name} achieved the strongest overall "
            f"delay prediction accuracy. Under current traffic and weather parameters, it projects "
            f"an estimated delay of {best_pred_val:.2f} minutes."
        )
    }


if __name__ == "__main__":
    res = train_and_evaluate_models()
    print("\n--- Model Comparison ---")
    for row in res["comparison_table"]:
        print(f"Rank {row['rank']}: {row['name']} | MAE={row['mae']} | RMSE={row['rmse']} | R²={row['r2']} | Acc±5m={row['accuracy_within_5_min']}%")
    print(f"\nBest Model: {res['best_model']}")
