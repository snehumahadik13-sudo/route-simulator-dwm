"""
ml/association_rules.py
Apriori association rule mining on accident and traffic data.
Discovers patterns like: weather+time → accident severity, etc.
"""
import os
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "ml_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_apriori(min_support=0.05, min_confidence=0.3, min_lift=1.0):
    print("\n" + "="*60)
    print("ASSOCIATION RULE MINING — Apriori Algorithm")
    print("="*60)

    from ml.db_loader import load_accident_data
    df = load_accident_data()
    print(f"Loaded {len(df):,} accident records for association mining.")

    # ── Encode categorical/ordinal fields as boolean items ──────────────────
    items = pd.DataFrame()

    # Weather conditions
    for w in df["weather"].dropna().unique():
        col = f"weather={w}"
        items[col] = (df["weather"] == w).astype(int)

    # Visibility
    for v in df["visibility"].dropna().unique():
        col = f"visibility={v}"
        items[col] = (df["visibility"] == v).astype(int)

    # Time of day (from hour or is_peak_hour)
    if "hour_24" in df.columns:
        items["time=peak"] = df["hour_24"].apply(lambda h: 1 if 8<=h<=11 or 17<=h<=20 else 0)
        items["time=night"] = df["hour_24"].apply(lambda h: 1 if 0<=h<6 else 0)
    elif "is_peak_hour" in df.columns:
        items["time=peak"] = df["is_peak_hour"].astype(int)

    # Road type
    if "road_type" in df.columns:
        for r in df["road_type"].dropna().unique():
            items[f"road={r}"] = (df["road_type"] == r).astype(int)

    # Severity
    if "accident_severity" in df.columns:
        for s in df["accident_severity"].dropna().unique():
            items[f"severity={s}"] = (df["accident_severity"] == s).astype(int)

    # Is fatal
    if "is_fatal" in df.columns:
        items["outcome=fatal"] = df["is_fatal"].astype(int)
    elif "accident_severity" in df.columns:
        items["outcome=fatal"] = (df["accident_severity"].str.lower() == "fatal").astype(int)

    # High casualties
    if "casualties" in df.columns:
        items["casualties=high"] = (df["casualties"].astype(float) >= 3).astype(int)

    # Traffic density
    if "traffic_density" in df.columns:
        for td in df["traffic_density"].dropna().unique():
            items[f"density={td}"] = (df["traffic_density"] == td).astype(int)

    # Weekend
    if "is_weekend" in df.columns:
        items["time=weekend"] = df["is_weekend"].astype(int)

    items = items.fillna(0).astype(bool)
    print(f"Transaction matrix: {items.shape[0]:,} rows × {items.shape[1]} items")

    try:
        from mlxtend.frequent_patterns import apriori, association_rules
        frequent_itemsets = apriori(
            items, min_support=min_support, use_colnames=True, max_len=4
        )
        if frequent_itemsets.empty:
            print("No frequent itemsets found at this support level. Lowering support...")
            frequent_itemsets = apriori(items, min_support=0.02, use_colnames=True, max_len=4)

        print(f"Found {len(frequent_itemsets):,} frequent itemsets (min_support={min_support})")

        if frequent_itemsets.empty:
            print("Still no frequent itemsets — data may be too sparse.")
            return []

        rules = association_rules(
            frequent_itemsets, metric="confidence", min_threshold=min_confidence
        )
        rules = rules[rules["lift"] >= min_lift].copy()
        rules = rules.sort_values("lift", ascending=False).head(50)

        print(f"\nTop Association Rules (min_conf={min_confidence}, min_lift={min_lift}):")
        print(f"{'Antecedents':<45} {'→'} {'Consequents':<30} {'Sup':>6} {'Conf':>6} {'Lift':>6}")
        print("-"*100)

        results = []
        for _, row in rules.iterrows():
            ant = ", ".join(sorted(row["antecedents"]))
            con = ", ".join(sorted(row["consequents"]))
            sup = float(row["support"])
            conf = float(row["confidence"])
            lift = float(row["lift"])
            print(f"  {ant[:43]:<45} → {con[:28]:<30} {sup:>6.3f} {conf:>6.3f} {lift:>6.3f}")
            results.append({
                "antecedents": ant, "consequents": con,
                "support": round(sup, 4),
                "confidence": round(conf, 4),
                "lift": round(lift, 4)
            })

        # Save results
        out_path = OUTPUT_DIR / "association_rules.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n✓ Association rules saved to: {out_path}")
        return results

    except ImportError:
        print("mlxtend not installed. Run: pip install mlxtend")
        return []


if __name__ == "__main__":
    run_apriori()
