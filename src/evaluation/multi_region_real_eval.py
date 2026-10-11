"""Multi-Region Evaluation on Real Test Period (Summer 2026).

Evaluates the LightGBM model against Naive Baseline on real out-of-sample
test intervals (June 1, 2026 - August 31, 2026) across key Ukrainian regions:
- Kyiv City (Capital)
- Kharkivska oblast (Frontline / Border)
- Dnipropetrovska oblast (Central-East)
- Odeska oblast (South / Sea)
- Lvivska oblast (Western Ukraine)
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
import lightgbm as lgb

from src.ingestion.alerts_loader import load_official_alerts_csv, resample_alerts_to_grid
from src.ingestion.telegram_multi_channel import (
    fetch_all_monitoring_channels,
    join_multi_channel_features_to_grid,
)
from src.feature_engineering import engineer_features
from src.train import temporal_split, find_optimal_threshold, PersistenceBaseline


REGIONS_TO_EVALUATE = [
    "Kyiv City",
    "Kharkivska oblast",
    "Dnipropetrovska oblast",
    "Odeska oblast",
    "Lvivska oblast",
]


def evaluate_region_on_real_period(
    region_name: str,
    start_date: str = "2025-01-01",
    end_date: str = "2026-09-01",
) -> dict:
    """Trains and evaluates LightGBM vs Baseline on real historical test period for a specific region."""
    # 1. Load alerts (all siren events across the target oblast)
    events_df = load_official_alerts_csv(
        filepath="data/alerts_official.csv",
        level=None,
        target_oblast=region_name,
        start_date=start_date,
        end_date=end_date,
    )
    if events_df.empty:
        return {"error": f"No events found for {region_name}"}

    start_grid = pd.to_datetime(start_date, utc=True)
    end_grid = pd.to_datetime(end_date, utc=True)

    # 2. Resample to 15-min regular grid
    grid_df = resample_alerts_to_grid(
        events_df=events_df,
        start_dt=start_grid,
        end_dt=end_grid,
        region_name=region_name,
    )

    # 3. Join multi-channel OSINT
    tg_df = fetch_all_monitoring_channels()
    grid_with_tg = join_multi_channel_features_to_grid(grid_df, tg_df)

    # 4. Feature engineering
    full_df = engineer_features(grid_with_tg, region_col="region_id")

    # Target: alert active in next 15m
    target_col = "target_alert_ahead_15m"
    full_df[target_col] = full_df["is_alert"].shift(-1)
    full_df = full_df.dropna(subset=[target_col]).reset_index(drop=True)
    full_df[target_col] = full_df[target_col].astype(int)

    feature_cols = [
        "hour_sin", "hour_cos", "day_of_week_sin", "day_of_week_cos",
        "alert_lag_15m", "alert_lag_1h", "alert_lag_3h", "alert_lag_6h", "alert_lag_24h",
        "rolling_duration_mean_7d",
        "tg_shahed", "tg_ballistics", "tg_aviation", "tg_mig31", "tg_missile",
        "tg_kyiv_targeted", "tg_activity_15m", "tg_activity_1h", "tg_channel_consensus",
    ]

    for f in feature_cols:
        full_df[f] = full_df[f].fillna(0.0)

    # 5. Temporal split (70% Train, 15% Val, 15% Test)
    train_df, val_df, test_df = temporal_split(full_df, train_frac=0.70, val_frac=0.15)

    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_val, y_val = val_df[feature_cols], val_df[target_col]
    X_test, y_test = test_df[feature_cols], test_df[target_col]

    # Baseline
    baseline = PersistenceBaseline(persistence_weight=0.90).fit(y_train)
    val_prob_base = baseline.predict_proba(val_df["alert_lag_15m"])
    test_prob_base = baseline.predict_proba(test_df["alert_lag_15m"])
    th_base = find_optimal_threshold(y_val.to_numpy(), val_prob_base)

    # LightGBM
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos = max(1.0, float(neg_count) / max(1, pos_count))

    lgbm = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=6,
        scale_pos_weight=scale_pos,
        random_state=42,
        verbosity=-1,
    )
    lgbm.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(25, verbose=False)])

    val_prob_lgb = lgbm.predict_proba(X_val)[:, 1]
    test_prob_lgb = lgbm.predict_proba(X_test)[:, 1]
    th_lgb = find_optimal_threshold(y_val.to_numpy(), val_prob_lgb)

    # Test metrics
    y_test_arr = y_test.to_numpy()
    pr_base = float(average_precision_score(y_test_arr, test_prob_base))
    pr_lgb = float(average_precision_score(y_test_arr, test_prob_lgb))

    brier_base = float(brier_score_loss(y_test_arr, test_prob_base))
    brier_lgb = float(brier_score_loss(y_test_arr, test_prob_lgb))

    preds_base = (test_prob_base >= th_base).astype(int)
    preds_lgb = (test_prob_lgb >= th_lgb).astype(int)

    f1_base = float(f1_score(y_test_arr, preds_base, zero_division=0))
    f1_lgb = float(f1_score(y_test_arr, preds_lgb, zero_division=0))

    rec_base = float(recall_score(y_test_arr, preds_base, zero_division=0))
    rec_lgb = float(recall_score(y_test_arr, preds_lgb, zero_division=0))

    prec_base = float(precision_score(y_test_arr, preds_base, zero_division=0))
    prec_lgb = float(precision_score(y_test_arr, preds_lgb, zero_division=0))

    # Stratified: New Alert Onset (Quiet slots at t_k)
    quiet_mask = (test_df["is_alert"] == 0).to_numpy()
    y_quiet = y_test_arr[quiet_mask]
    if y_quiet.sum() > 0:
        pr_onset_base = float(average_precision_score(y_quiet, test_prob_base[quiet_mask]))
        pr_onset_lgb = float(average_precision_score(y_quiet, test_prob_lgb[quiet_mask]))
        onset_rate = float(y_quiet.mean())
    else:
        pr_onset_base, pr_onset_lgb, onset_rate = 0.0, 0.0, 0.0

    return {
        "region": region_name,
        "events_count": len(events_df),
        "test_intervals": len(test_df),
        "test_alert_prevalence": round(float(y_test.mean()) * 100, 2),
        "baseline": {
            "pr_auc": round(pr_base, 4),
            "brier_score": round(brier_base, 4),
            "f1": round(f1_base, 4),
            "recall": round(rec_base * 100, 1),
            "precision": round(prec_base * 100, 1),
            "onset_pr_auc": round(pr_onset_base, 4),
        },
        "lightgbm": {
            "pr_auc": round(pr_lgb, 4),
            "brier_score": round(brier_lgb, 4),
            "f1": round(f1_lgb, 4),
            "recall": round(rec_lgb * 100, 1),
            "precision": round(prec_lgb * 100, 1),
            "onset_pr_auc": round(pr_onset_lgb, 4),
        },
        "onset_random_rate": round(onset_rate * 100, 2),
    }


def run_all_regions_evaluation():
    results = []
    print("=" * 70)
    print("ОЦІНКА МОДЕЛІ НА РЕАЛЬНОМУ ТЕСТОВОМУ ПЕРІОДІ (ЧЕРВЕНЬ - СЕРПЕНЬ 2026)")
    print("=" * 70)
    for reg in REGIONS_TO_EVALUATE:
        print(f"Аналіз регіону: {reg}...")
        r = evaluate_region_on_real_period(reg)
        results.append(r)

    # Save to JSON
    out_file = Path("reports/multi_region_real_results.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=float)

    return results


if __name__ == "__main__":
    run_all_regions_evaluation()
