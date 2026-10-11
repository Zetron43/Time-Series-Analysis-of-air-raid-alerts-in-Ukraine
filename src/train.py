"""Model Training, Validation, and Evaluation Module.

Comparative Analysis:
1. Naive Baseline (Persistence / Historical Prior Probability).
2. Gradient Boosting (LightGBM Classifier).

Strict Temporal Validation Invariants:
- Chronological Split: 70% Train, 15% Validation, 15% Test (No shuffle).
- Threshold Optimization: Threshold theta* tuned exclusively on Validation set,
  then evaluated out-of-sample on Test set.
- Metrics: PR-AUC (Average Precision), Brier Score, and Optimal F1 (Accuracy is forbidden).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
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

from src.feature_engineering import engineer_features


@dataclass
class EvaluationMetrics:
    model_name: str
    split_name: str
    pr_auc: float
    brier_score: float
    optimal_threshold: float
    f1_at_optimal: float
    precision_at_optimal: float
    recall_at_optimal: float
    confusion_matrix: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "split_name": self.split_name,
            "pr_auc": round(self.pr_auc, 4),
            "brier_score": round(self.brier_score, 4),
            "optimal_threshold": round(self.optimal_threshold, 4),
            "f1_at_optimal": round(self.f1_at_optimal, 4),
            "precision_at_optimal": round(self.precision_at_optimal, 4),
            "recall_at_optimal": round(self.recall_at_optimal, 4),
            "confusion_matrix": self.confusion_matrix.tolist(),
        }


def temporal_split(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
    timestamp_col: str = "timestamp",
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Strict chronological temporal split into Train, Validation, and Test sets.

    Guarantees:
    - max(Train_timestamps) < min(Val_timestamps) <= max(Val_timestamps) < min(Test_timestamps)
    - Zero data shuffling.

    Args:
        df: Input DataFrame (must contain timestamp_col).
        train_frac: Fraction of chronological observations for training (e.g. 0.70).
        val_frac: Fraction of chronological observations for validation (e.g. 0.15).
        timestamp_col: Name of the timestamp column.

    Returns:
        Tuple of (df_train, df_val, df_test).
    """
    df_sorted = df.sort_values(by=timestamp_col).reset_index(drop=True)
    n = len(df_sorted)

    n_train = int(n * train_frac)
    n_val = int(n * val_frac)

    df_train = df_sorted.iloc[:n_train].copy()
    df_val = df_sorted.iloc[n_train : n_train + n_val].copy()
    df_test = df_sorted.iloc[n_train + n_val :].copy()

    # Integrity verification
    assert df_train[timestamp_col].max() < df_val[timestamp_col].min(), (
        "Temporal leakage detected: Train and Val timestamps overlap!"
    )
    assert df_val[timestamp_col].max() < df_test[timestamp_col].min(), (
        "Temporal leakage detected: Val and Test timestamps overlap!"
    )

    return df_train, df_val, df_test


def find_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    min_threshold: float = 0.05,
    max_threshold: float = 0.95,
    num_steps: int = 100,
) -> float:
    """Find the probability threshold that maximizes F1-Score on validation set.

    Args:
        y_true: Binary ground truth array.
        y_prob: Predicted probability array in [0, 1].
        min_threshold: Minimum threshold to evaluate.
        max_threshold: Maximum threshold to evaluate.
        num_steps: Number of grid steps.

    Returns:
        Optimal threshold theta*.
    """
    thresholds = np.linspace(min_threshold, max_threshold, num_steps)
    best_f1 = -1.0
    best_th = 0.50

    for th in thresholds:
        preds = (y_prob >= th).astype(int)
        score = f1_score(y_true, preds, zero_division=0)
        if score > best_f1:
            best_f1 = score
            best_th = th

    return float(best_th)


def evaluate_model(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    model_name: str,
    split_name: str,
    threshold: float,
) -> EvaluationMetrics:
    """Compute strictly allowed metrics (PR-AUC, Brier Score, F1, Precision, Recall).

    ACCURACY IS STRICTLY FORBIDDEN due to class imbalance!
    """
    pr_auc = float(average_precision_score(y_true, y_prob))
    brier = float(brier_score_loss(y_true, y_prob))

    preds = (y_prob >= threshold).astype(int)
    f1 = float(f1_score(y_true, preds, zero_division=0))
    prec = float(precision_score(y_true, preds, zero_division=0))
    rec = float(recall_score(y_true, preds, zero_division=0))
    cm = confusion_matrix(y_true, preds)

    return EvaluationMetrics(
        model_name=model_name,
        split_name=split_name,
        pr_auc=pr_auc,
        brier_score=brier,
        optimal_threshold=threshold,
        f1_at_optimal=f1,
        precision_at_optimal=prec,
        recall_at_optimal=rec,
        confusion_matrix=cm,
    )


class PersistenceBaseline:
    """Naive persistence baseline: predicts past known state smoothed with train prior."""

    def __init__(self, persistence_weight: float = 0.90):
        self.persistence_weight = persistence_weight
        self.prior_prob: float = 0.5

    def fit(self, y_train: pd.Series):
        self.prior_prob = float(y_train.mean())
        return self

    def predict_proba(self, lag_series: pd.Series) -> np.ndarray:
        # Fill missing initial lag with historical prior
        cleaned_lags = lag_series.fillna(self.prior_prob).to_numpy(dtype=float)
        # Probabilistic mixture between persistence and prior
        probs = self.persistence_weight * cleaned_lags + (1.0 - self.persistence_weight) * self.prior_prob
        return np.clip(probs, 0.001, 0.999)


def train_and_evaluate(
    df: pd.DataFrame,
    target_horizon_steps: int = 1,  # 1 step = 15m ahead
    feature_cols: Optional[list[str]] = None,
    output_dir: str = "reports",
) -> dict[str, Any]:
    """Complete temporal training, tuning, and evaluation pipeline.

    1. Formulates target (e.g. next 15-min alert state).
    2. Performs strict 70/15/15 chronological split.
    3. Fits Persistence Baseline.
    4. Trains LightGBM with early stopping on Validation set.
    5. Tunes decision thresholds exclusively on Validation set.
    6. Evaluates both models out-of-sample on Test set.
    7. Plots Confusion Matrices and Precision-Recall Curves.

    Args:
        df: Prepared DataFrame with features.
        target_horizon_steps: Number of future 15-min steps ahead to predict (default: 1 = 15 min).
        feature_cols: List of feature names to use.
        output_dir: Directory to save plots and reports.

    Returns:
        Dictionary containing test metrics and model summaries.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    df_work = df.copy()

    # Formulate target: whether alert is active at t + horizon
    target_col = f"target_alert_ahead_{target_horizon_steps * 15}m"
    if "region_id" in df_work.columns:
        df_work[target_col] = (
            df_work.groupby("region_id")["is_alert"]
            .shift(-target_horizon_steps)
        )
    else:
        df_work[target_col] = df_work["is_alert"].shift(-target_horizon_steps)

    # Drop end rows without future target label
    df_work = df_work.dropna(subset=[target_col]).reset_index(drop=True)
    df_work[target_col] = df_work[target_col].astype(int)

    # 1. Temporal Split (70% Train, 15% Val, 15% Test)
    train_df, val_df, test_df = temporal_split(df_work, train_frac=0.70, val_frac=0.15)

    # Drop warmup rows where lag/rolling features are NaN in Train
    if feature_cols is None:
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
        ]

    # Impute missing warm-up lags with 0.0 to prevent sample loss
    for f in feature_cols:
        train_df[f] = train_df[f].fillna(0.0)
        val_df[f] = val_df[f].fillna(0.0)
        test_df[f] = test_df[f].fillna(0.0)

    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_val, y_val = val_df[feature_cols], val_df[target_col]
    X_test, y_test = test_df[feature_cols], test_df[target_col]

    # --- Approach 1: Naive Persistence Baseline ---
    baseline = PersistenceBaseline(persistence_weight=0.90)
    baseline.fit(y_train)

    val_prob_base = baseline.predict_proba(val_df["alert_lag_15m"])
    test_prob_base = baseline.predict_proba(test_df["alert_lag_15m"])

    th_baseline = find_optimal_threshold(y_val.to_numpy(), val_prob_base)
    eval_base_test = evaluate_model(
        y_true=y_test.to_numpy(),
        y_prob=test_prob_base,
        model_name="Naive Persistence Baseline",
        split_name="Test",
        threshold=th_baseline,
    )

    # --- Approach 2: LightGBM Gradient Boosting ---
    # Handle class imbalance via scale_pos_weight
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos_weight = max(1.0, float(neg_count) / max(1, pos_count))

    lgbm = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=6,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        verbosity=-1,
    )

    lgbm.fit(
        X_train,
        y_train,
        eval_X=X_val,
        eval_y=y_val,
        callbacks=[lgb.early_stopping(stopping_rounds=25, verbose=False)],
    )

    val_prob_lgb = lgbm.predict_proba(X_val)[:, 1]
    test_prob_lgb = lgbm.predict_proba(X_test)[:, 1]

    # Optimize threshold on Validation ONLY
    th_lgb = find_optimal_threshold(y_val.to_numpy(), val_prob_lgb)
    eval_lgb_test = evaluate_model(
        y_true=y_test.to_numpy(),
        y_prob=test_prob_lgb,
        model_name="LightGBM Classifier",
        split_name="Test",
        threshold=th_lgb,
    )

    # --- Plotting Visualizations ---
    # 1. Precision-Recall Curves
    fig_pr, ax_pr = plt.subplots(figsize=(8, 6))
    
    # Baseline PR curve
    p_base, r_base, _ = precision_recall_curve(y_test, test_prob_base)
    ax_pr.plot(
        r_base, p_base,
        label=f"Naive Baseline (PR-AUC = {eval_base_test.pr_auc:.3f})",
        linestyle="--", color="gray",
    )

    # LightGBM PR curve
    p_lgb, r_lgb, _ = precision_recall_curve(y_test, test_prob_lgb)
    ax_pr.plot(
        r_lgb, p_lgb,
        label=f"LightGBM (PR-AUC = {eval_lgb_test.pr_auc:.3f})",
        color="crimson", linewidth=2,
    )

    # No-skill line (positive class proportion)
    no_skill = float(y_test.mean())
    ax_pr.axhline(no_skill, linestyle=":", color="black", alpha=0.6, label=f"No Skill ({no_skill:.2f})")

    ax_pr.set_title("Precision-Recall Curve on Test Set (15-min Forecast)")
    ax_pr.set_xlabel("Recall")
    ax_pr.set_ylabel("Precision")
    ax_pr.set_ylim([0.0, 1.05])
    ax_pr.set_xlim([0.0, 1.0])
    ax_pr.legend(loc="upper right")
    ax_pr.grid(True, linestyle="--", alpha=0.5)

    pr_curve_path = out_path / "precision_recall_curve.png"
    fig_pr.savefig(pr_curve_path, dpi=200, bbox_inches="tight")
    plt.close(fig_pr)

    # 2. Confusion Matrices Comparison
    fig_cm, axes_cm = plt.subplots(1, 2, figsize=(12, 5))

    ConfusionMatrixDisplay(eval_base_test.confusion_matrix, display_labels=["Спокійно", "Тривога"]).plot(
        ax=axes_cm[0], cmap="Blues", colorbar=False
    )
    axes_cm[0].set_title(f"Baseline (Threshold={th_baseline:.2f})")

    ConfusionMatrixDisplay(eval_lgb_test.confusion_matrix, display_labels=["Спокійно", "Тривога"]).plot(
        ax=axes_cm[1], cmap="Purples", colorbar=False
    )
    axes_cm[1].set_title(f"LightGBM (Threshold={th_lgb:.2f})")

    fig_cm.suptitle("Confusion Matrix on Test Set", fontsize=14)
    cm_path = out_path / "confusion_matrix.png"
    fig_cm.savefig(cm_path, dpi=200, bbox_inches="tight")
    plt.close(fig_cm)

    results = {
        "dataset_summary": {
            "total_rows": len(df_work),
            "train_rows": len(train_df),
            "val_rows": len(val_df),
            "test_rows": len(test_df),
            "test_positive_prevalence": round(float(y_test.mean()), 4),
        },
        "baseline_metrics": eval_base_test.to_dict(),
        "lightgbm_metrics": eval_lgb_test.to_dict(),
        "artifacts": {
            "pr_curve_plot": str(pr_curve_path),
            "confusion_matrix_plot": str(cm_path),
        },
    }

    return results


if __name__ == "__main__":
    from tests.test_feature_engineering import _generate_synthetic_grid

    print("Generating synthetic 15-minute time series (60 days)...")
    df_raw = _generate_synthetic_grid(start_time="2026-01-01 00:00:00", days=60, region_id=1, seed=42)
    print("Computing zero-leakage causal features...")
    df_feat = engineer_features(df_raw)

    print("Running training and comparative evaluation...")
    res = train_and_evaluate(df_feat, output_dir="reports")

    print("\n--- RESULTS SUMMARY ON TEST SET ---")
    print(f"Total Observations: {res['dataset_summary']['total_rows']} (Test: {res['dataset_summary']['test_rows']})")
    print(f"Positive Alert Prevalence: {res['dataset_summary']['test_positive_prevalence'] * 100:.1f}%\n")

    b_m = res["baseline_metrics"]
    l_m = res["lightgbm_metrics"]

    print(f"1. Naive Persistence Baseline:")
    print(f"   PR-AUC:         {b_m['pr_auc']:.4f}")
    print(f"   Brier Score:    {b_m['brier_score']:.4f} (lower is better)")
    print(f"   Optimal Thresh: {b_m['optimal_threshold']:.2f}")
    print(f"   F1 at Thresh:   {b_m['f1_at_optimal']:.4f} (Prec: {b_m['precision_at_optimal']:.4f}, Rec: {b_m['recall_at_optimal']:.4f})")

    print(f"\n2. LightGBM Gradient Boosting:")
    print(f"   PR-AUC:         {l_m['pr_auc']:.4f}")
    print(f"   Brier Score:    {l_m['brier_score']:.4f} (lower is better)")
    print(f"   Optimal Thresh: {l_m['optimal_threshold']:.2f}")
    print(f"   F1 at Thresh:   {l_m['f1_at_optimal']:.4f} (Prec: {l_m['precision_at_optimal']:.4f}, Rec: {l_m['recall_at_optimal']:.4f})")

    print(f"\nPlots saved successfully to: {res['artifacts']['pr_curve_plot']} and {res['artifacts']['confusion_matrix_plot']}")
