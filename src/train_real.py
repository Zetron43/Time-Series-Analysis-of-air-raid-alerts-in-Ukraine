"""Retraining Pipeline on Real Data: alerts.in.ua dataset and @kpszsu Telegram intelligence.

Features:
- Official Ukrainian Air Raid Alerts (Kyiv City / nationwide).
- NLP threat features from https://t.me/kpszsu (Shahed, Ballistics, Aviation, MiG-31).
- Strict Zero-Leakage: Causal point-in-time join, no lookahead bias.
- Stratified Evaluation: Dissecting performance on quiet periods (new alert onset)
  vs active periods (alert continuation).
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.metrics import (
    precision_recall_curve,
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    confusion_matrix,
    ConfusionMatrixDisplay,
)
import lightgbm as lgb

from src.ingestion.alerts_loader import load_official_alerts_csv, resample_alerts_to_grid
from src.ingestion.telegram_multi_channel import (
    fetch_all_monitoring_channels,
    join_multi_channel_features_to_grid,
)
from src.feature_engineering import engineer_features
from src.train import (
    temporal_split,
    find_optimal_threshold,
    evaluate_model,
    PersistenceBaseline,
)


def run_real_training(
    target_oblast: str = "Kyiv City",
    start_date: str = "2025-01-01",
    end_date: str = "2026-09-01",
    output_dir: str = "reports",
) -> dict:
    """Executes the complete retraining pipeline on real historical alerts and multi-channel OSINT."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"1. Loading official alerts for '{target_oblast}' ({start_date} to {end_date})...")
    events_df = load_official_alerts_csv(
        filepath="data/alerts_official.csv",
        target_oblast=target_oblast,
        start_date=start_date,
        end_date=end_date,
    )
    print(f"   Loaded {len(events_df)} official alert events.")

    start_grid = pd.to_datetime(start_date, utc=True)
    end_grid = pd.to_datetime(end_date, utc=True)
    print("2. Resampling continuous events into causal 15-minute time grid...")
    grid_df = resample_alerts_to_grid(
        events_df=events_df,
        start_dt=start_grid,
        end_dt=end_grid,
        region_name=target_oblast,
    )
    alert_rate = grid_df["is_alert"].mean() * 100.0
    print(f"   Grid generated: {len(grid_df)} intervals. Active alert rate: {alert_rate:.2f}%.")

    print("3. Ingesting multi-channel OSINT: @kpszsu, @war_monitor, @raketa_trevoga...")
    tg_df = fetch_all_monitoring_channels()
    print(f"   Ingested {len(tg_df)} total intelligence posts across 3 channels.")

    print("4. Applying causal point-in-time join for multi-channel OSINT signals...")
    grid_with_tg = join_multi_channel_features_to_grid(
        grid_df=grid_df,
        messages_df=tg_df,
    )

    print("5. Computing causal lag and rolling features...")
    full_df = engineer_features(grid_with_tg, region_col="region_id")

    # Target: 1 step (15 min) ahead alert state
    target_col = "target_alert_ahead_15m"
    full_df[target_col] = full_df["is_alert"].shift(-1)
    full_df = full_df.dropna(subset=[target_col]).reset_index(drop=True)
    full_df[target_col] = full_df[target_col].astype(int)

    feature_cols = [
        "hour_sin",
        "hour_cos",
        "day_of_week_sin",
        "day_of_week_cos",
        "alert_lag_15m",
        "alert_lag_1h",
        "alert_lag_3h",
        "alert_lag_6h",
        "alert_lag_24h",
        "rolling_duration_mean_7d",
        "tg_shahed",
        "tg_ballistics",
        "tg_aviation",
        "tg_mig31",
        "tg_missile",
        "tg_kyiv_targeted",
        "tg_activity_15m",
        "tg_activity_1h",
        "tg_channel_consensus",
    ]

    # Fill initial warmup periods with 0.0
    for f in feature_cols:
        full_df[f] = full_df[f].fillna(0.0)

    # 6. Strict Chronological Temporal Split (70% Train, 15% Val, 15% Test)
    train_df, val_df, test_df = temporal_split(full_df, train_frac=0.70, val_frac=0.15)
    print(f"6. Temporal Split: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")
    print(f"   Test date range: {test_df['timestamp'].min()} to {test_df['timestamp'].max()}")

    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_val, y_val = val_df[feature_cols], val_df[target_col]
    X_test, y_test = test_df[feature_cols], test_df[target_col]

    # --- Baseline ---
    baseline = PersistenceBaseline(persistence_weight=0.90).fit(y_train)
    val_prob_base = baseline.predict_proba(val_df["alert_lag_15m"])
    test_prob_base = baseline.predict_proba(test_df["alert_lag_15m"])

    th_base = find_optimal_threshold(y_val.to_numpy(), val_prob_base)
    eval_base = evaluate_model(y_test.to_numpy(), test_prob_base, "Baseline", "Test", th_base)

    # --- LightGBM ---
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos = max(1.0, float(neg_count) / max(1, pos_count))

    lgbm = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=400,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=6,
        scale_pos_weight=scale_pos,
        random_state=42,
        verbosity=-1,
    )
    lgbm.fit(
        X_train,
        y_train,
        eval_X=X_val,
        eval_y=y_val,
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    val_prob_lgb = lgbm.predict_proba(X_val)[:, 1]
    test_prob_lgb = lgbm.predict_proba(X_test)[:, 1]

    th_lgb = find_optimal_threshold(y_val.to_numpy(), val_prob_lgb)
    eval_lgb = evaluate_model(y_test.to_numpy(), test_prob_lgb, "LightGBM (Real Data)", "Test", th_lgb)

    # Feature importances
    importances = dict(zip(feature_cols, lgbm.feature_importances_.tolist()))
    sorted_importances = dict(sorted(importances.items(), key=lambda item: item[1], reverse=True))

    # --- Stratified Error Analysis (Testing Hypothesis 1: "Паразит на інерції") ---
    # Stratum A: Quiet periods at t_k (Testing ability to predict NEW alerts)
    quiet_mask = (test_df["is_alert"] == 0).to_numpy()
    y_test_quiet = y_test.to_numpy()[quiet_mask]
    prob_lgb_quiet = test_prob_lgb[quiet_mask]
    prob_base_quiet = test_prob_base[quiet_mask]

    pr_auc_quiet_lgb = float(average_precision_score(y_test_quiet, prob_lgb_quiet)) if y_test_quiet.sum() > 0 else 0.0
    pr_auc_quiet_base = float(average_precision_score(y_test_quiet, prob_base_quiet)) if y_test_quiet.sum() > 0 else 0.0
    prevalence_quiet = float(y_test_quiet.mean())

    # Stratum B: Active periods at t_k (Testing continuation/all-clear prediction)
    active_mask = (test_df["is_alert"] == 1).to_numpy()
    y_test_active = y_test.to_numpy()[active_mask]
    prob_lgb_active = test_prob_lgb[active_mask]
    prob_base_active = test_prob_base[active_mask]

    pr_auc_active_lgb = float(average_precision_score(y_test_active, prob_lgb_active)) if y_test_active.sum() > 0 else 0.0
    pr_auc_active_base = float(average_precision_score(y_test_active, prob_base_active)) if y_test_active.sum() > 0 else 0.0

    # --- Plots ---
    # 1. PR Curve
    fig_pr, ax_pr = plt.subplots(figsize=(8, 6))
    p_b, r_b, _ = precision_recall_curve(y_test, test_prob_base)
    ax_pr.plot(r_b, p_b, label=f"Baseline (PR-AUC = {eval_base.pr_auc:.3f})", linestyle="--", color="gray")

    p_l, r_l, _ = precision_recall_curve(y_test, test_prob_lgb)
    ax_pr.plot(r_l, p_l, label=f"LightGBM Real (PR-AUC = {eval_lgb.pr_auc:.3f})", color="royalblue", linewidth=2)

    ax_pr.axhline(float(y_test.mean()), linestyle=":", color="black", alpha=0.6, label=f"No Skill ({float(y_test.mean()):.2f})")
    ax_pr.set_title("PR Curve on Real Data (Kyiv City, alerts.in.ua + @kpszsu)")
    ax_pr.set_xlabel("Recall")
    ax_pr.set_ylabel("Precision")
    ax_pr.legend()
    ax_pr.grid(True, linestyle="--", alpha=0.5)

    pr_path = out_path / "real_data_pr_curve.png"
    fig_pr.savefig(pr_path, dpi=200, bbox_inches="tight")
    plt.close(fig_pr)

    # 2. Confusion Matrix
    fig_cm, axes_cm = plt.subplots(1, 2, figsize=(12, 5))
    ConfusionMatrixDisplay(eval_base.confusion_matrix, display_labels=["Спокійно", "Тривога"]).plot(
        ax=axes_cm[0], cmap="Blues", colorbar=False
    )
    axes_cm[0].set_title(f"Baseline (Threshold={th_base:.2f})")

    ConfusionMatrixDisplay(eval_lgb.confusion_matrix, display_labels=["Спокійно", "Тривога"]).plot(
        ax=axes_cm[1], cmap="Purples", colorbar=False
    )
    axes_cm[1].set_title(f"LightGBM (Threshold={th_lgb:.2f})")
    fig_cm.suptitle("Confusion Matrix on Real Test Set (Kyiv City)", fontsize=14)

    cm_path = out_path / "real_data_confusion_matrix.png"
    fig_cm.savefig(cm_path, dpi=200, bbox_inches="tight")
    plt.close(fig_cm)

    results = {
        "dataset": {
            "target_oblast": target_oblast,
            "period": f"{start_date} to {end_date}",
            "total_intervals": len(full_df),
            "test_intervals": len(test_df),
            "test_alert_prevalence": round(float(y_test.mean()), 4),
        },
        "overall_metrics": {
            "baseline": eval_base.to_dict(),
            "lightgbm": eval_lgb.to_dict(),
        },
        "stratified_analysis": {
            "quiet_subset": {
                "description": "Прогнозування ПОЧАТКУ нової тривоги для спокійних слотів",
                "sample_count": int(quiet_mask.sum()),
                "positive_prevalence": round(prevalence_quiet, 4),
                "baseline_pr_auc": round(pr_auc_quiet_base, 4),
                "lightgbm_pr_auc": round(pr_auc_quiet_lgb, 4),
            },
            "active_subset": {
                "description": "Прогнозування ПРОДОВЖЕННЯ тривоги для активних слотів",
                "sample_count": int(active_mask.sum()),
                "baseline_pr_auc": round(pr_auc_active_base, 4),
                "lightgbm_pr_auc": round(pr_auc_active_lgb, 4),
            },
        },
        "top_features": list(sorted_importances.items())[:8],
        "artifacts": {
            "pr_curve": str(pr_path),
            "confusion_matrix": str(cm_path),
        },
    }

    return results


if __name__ == "__main__":
    res = run_real_training()
    print("\n=================== REAL DATA RETRAINING RESULTS ===================")
    print(f"Target: {res['dataset']['target_oblast']} | Period: {res['dataset']['period']}")
    print(f"Total Intervals: {res['dataset']['total_intervals']} (Test Set: {res['dataset']['test_intervals']})")
    print(f"Positive Alert Prevalence: {res['dataset']['test_alert_prevalence'] * 100:.1f}%\n")

    b = res["overall_metrics"]["baseline"]
    l = res["overall_metrics"]["lightgbm"]

    print("--- 1. Загальні метрики на Test Set ---")
    print(f"Baseline: PR-AUC={b['pr_auc']:.4f}, Brier={b['brier_score']:.4f}, F1={b['f1_at_optimal']:.4f} (Rec={b['recall_at_optimal']:.4f}, Prec={b['precision_at_optimal']:.4f})")
    print(f"LightGBM: PR-AUC={l['pr_auc']:.4f}, Brier={l['brier_score']:.4f}, F1={l['f1_at_optimal']:.4f} (Rec={l['recall_at_optimal']:.4f}, Prec={l['precision_at_optimal']:.4f})")

    st = res["stratified_analysis"]
    print("\n--- 2. Стратифікований аналіз (Перевірка гіпотези інерції) ---")
    sq = st["quiet_subset"]
    sa = st["active_subset"]
    print(f"[A] Початок НОВОЇ тривоги (спокійний стан на t_k):")
    print(f"    Частка початку тривог: {sq['positive_prevalence'] * 100:.2f}% (No-Skill Baseline)")
    print(f"    Baseline PR-AUC:       {sq['baseline_pr_auc']:.4f}")
    print(f"    LightGBM PR-AUC:       {sq['lightgbm_pr_auc']:.4f}")
    print(f"[B] Продовження існуючої тривоги (активний стан на t_k):")
    print(f"    Baseline PR-AUC:       {sa['baseline_pr_auc']:.4f}")
    print(f"    LightGBM PR-AUC:       {sa['lightgbm_pr_auc']:.4f}")

    print("\n--- 3. Топ найважливіших ознак моделі ---")
    for feat, imp in res["top_features"]:
        print(f"    • {feat:25s}: {imp}")

    print(f"\nГрафіки збережено: {res['artifacts']['pr_curve']} та {res['artifacts']['confusion_matrix']}")
