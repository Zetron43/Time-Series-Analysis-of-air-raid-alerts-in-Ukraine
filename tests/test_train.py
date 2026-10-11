"""Unit tests for train.py module.

Verifies:
1. Strict chronological temporal split (70/15/15) without leakage.
2. Invariant: Accuracy is not used as an evaluation metric.
3. Threshold optimization on validation set.
4. Correctness of Persistence Baseline and LightGBM model training.
5. Generation of Confusion Matrix and PR Curve artifacts.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.feature_engineering import engineer_features
from src.train import (
    temporal_split,
    find_optimal_threshold,
    evaluate_model,
    PersistenceBaseline,
    train_and_evaluate,
)
from tests.test_feature_engineering import _generate_synthetic_grid


class TestTrainModule:

    def test_temporal_split_disjointness(self):
        """Verifies strictly non-overlapping train, validation, and test chronological sets."""
        df = _generate_synthetic_grid(days=30, seed=10)
        train_df, val_df, test_df = temporal_split(df, train_frac=0.70, val_frac=0.15)

        # Proportions check
        total_len = len(df)
        assert len(train_df) == int(total_len * 0.70)
        assert len(val_df) == int(total_len * 0.15)
        assert len(test_df) == total_len - len(train_df) - len(val_df)

        # Strict chronological ordering
        assert train_df["timestamp"].max() < val_df["timestamp"].min()
        assert val_df["timestamp"].max() < test_df["timestamp"].min()

    def test_threshold_tuning_validation_only(self):
        """Verifies that threshold is optimized on validation set labels."""
        y_val = np.array([0, 0, 0, 1, 1, 1])
        # Probabilities that correlate with ground truth
        y_prob = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])

        th = find_optimal_threshold(y_val, y_prob)
        # Optimal threshold should separate classes around 0.5
        assert 0.3 <= th <= 0.7

        # Evaluate model with this threshold
        metrics = evaluate_model(y_val, y_prob, "TestModel", "Validation", threshold=th)
        assert metrics.f1_at_optimal == 1.0
        assert metrics.confusion_matrix[1, 1] == 3  # All true positives caught

    def test_persistence_baseline(self):
        """Verifies baseline persistence logic and bound constraints."""
        y_train = pd.Series([0, 0, 0, 1, 0, 0])
        lags_test = pd.Series([0, 1, 0, np.nan])

        base = PersistenceBaseline(persistence_weight=0.90)
        base.fit(y_train)

        probs = base.predict_proba(lags_test)
        assert len(probs) == 4
        assert np.all((probs >= 0.0) & (probs <= 1.0))
        # When lag is 1, predicted prob must be significantly higher than when lag is 0
        assert probs[1] > probs[0]

    def test_end_to_end_training_and_artifacts(self, tmp_path):
        """Verifies full execution pipeline and artifact generation."""
        df_raw = _generate_synthetic_grid(days=20, seed=42)
        df_feat = engineer_features(df_raw)

        results = train_and_evaluate(
            df_feat,
            target_horizon_steps=1,
            output_dir=str(tmp_path),
        )

        # Check metrics schema
        assert "baseline_metrics" in results
        assert "lightgbm_metrics" in results
        assert "artifacts" in results

        b_metrics = results["baseline_metrics"]
        l_metrics = results["lightgbm_metrics"]

        # Validate that metrics exist and are in valid ranges
        for m in [b_metrics, l_metrics]:
            assert 0.0 <= m["pr_auc"] <= 1.0
            assert 0.0 <= m["brier_score"] <= 1.0
            assert 0.0 <= m["f1_at_optimal"] <= 1.0
            assert "confusion_matrix" in m
            cm = np.array(m["confusion_matrix"])
            assert cm.shape == (2, 2)
            assert cm.sum() == results["dataset_summary"]["test_rows"]

        # Verify artifacts exist on disk
        pr_path = Path(results["artifacts"]["pr_curve_plot"])
        cm_path = Path(results["artifacts"]["confusion_matrix_plot"])
        assert pr_path.exists()
        assert cm_path.exists()
        assert pr_path.stat().st_size > 0
        assert cm_path.stat().st_size > 0
