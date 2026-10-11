"""Unit tests for feature engineering module.

Includes rigorous validation of:
1. Zero Lookahead Bias (Data Leakage Sentinel Test).
2. Trigonometric accuracy of cyclic calendar features.
3. Correctness of causal step lags.
4. Causal isolation of 7-day rolling window statistics.
5. Partition integrity across multiple regions.
"""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from src.feature_engineering import (
    engineer_features,
    add_calendar_features,
    add_alert_lags,
    add_rolling_alert_duration_7d,
    GRID_STEP_MINUTES,
    STEPS_PER_HOUR,
    ROLLING_7D_STEPS,
)


def _generate_synthetic_grid(
    start_time: str = "2026-01-01 00:00:00",
    days: int = 14,
    region_id: int = 1,
    seed: int = 42,
) -> pd.DataFrame:
    """Helper to generate a realistic 15-minute time grid."""
    np.random.seed(seed)
    start_dt = pd.to_datetime(start_time)
    periods = days * 24 * (60 // GRID_STEP_MINUTES)
    timestamps = pd.date_range(start=start_dt, periods=periods, freq="15min")

    # Generate pseudo-random alerts (e.g. ~10% active rate)
    is_alert = (np.random.rand(periods) > 0.90).astype(int)
    durations = is_alert * np.random.uniform(5.0, 15.0, size=periods)

    return pd.DataFrame({
        "timestamp": timestamps,
        "region_id": region_id,
        "is_alert": is_alert,
        "alert_duration_minutes": durations,
    })


class TestFeatureEngineering:

    def test_no_lookahead_bias(self):
        """CRITICAL TEST: Verifies strict absence of lookahead bias (Data Leakage).

        If any future observation (t > t_cutoff) is modified or corrupted,
        ALL engineered features at t <= t_cutoff MUST remain 100% IDENTICAL.
        """
        # 1. Generate 14 days of historical 15-minute data
        df_original = _generate_synthetic_grid(days=14, seed=123)

        # 2. Select cutoff point at Day 10 (00:00)
        cutoff_dt = pd.to_datetime("2026-01-11 00:00:00")
        past_mask = df_original["timestamp"] <= cutoff_dt
        future_mask = df_original["timestamp"] > cutoff_dt

        # Ensure we have both past and future rows
        assert past_mask.sum() > 0
        assert future_mask.sum() > 0

        # 3. Compute baseline features on untouched dataset
        features_original = engineer_features(df_original)

        # 4. Construct a heavily corrupted/mutated version of future data ONLY
        df_mutated = df_original.copy()

        # Invert future alerts, inject massive duration spikes in the future
        df_mutated.loc[future_mask, "is_alert"] = 1 - df_mutated.loc[future_mask, "is_alert"]
        df_mutated.loc[future_mask, "alert_duration_minutes"] = 9999.0

        # 5. Compute features on mutated dataset
        features_mutated = engineer_features(df_mutated)

        # 6. Extract pre-cutoff slices
        slice_original = features_original[features_original["timestamp"] <= cutoff_dt]
        slice_mutated = features_mutated[features_mutated["timestamp"] <= cutoff_dt]

        # 7. Check that all engineered feature columns are strictly identical
        engineered_columns = [
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

        for col in engineered_columns:
            # Check for non-null and NaN consistency
            orig_vals = slice_original[col].to_numpy()
            mut_vals = slice_mutated[col].to_numpy()

            np.testing.assert_allclose(
                orig_vals,
                mut_vals,
                equal_nan=True,
                rtol=1e-12,
                atol=1e-12,
                err_msg=f"Lookahead bias detected in feature: '{col}'! Past values changed due to future mutation.",
            )

    def test_calendar_features(self):
        """Checks trigonometric correctness and cyclic boundaries."""
        sample_times = pd.to_datetime([
            "2026-01-01 00:00:00",  # Thursday, 00:00
            "2026-01-01 06:00:00",  # 06:00
            "2026-01-01 12:00:00",  # 12:00
            "2026-01-01 18:00:00",  # 18:00
        ])
        df = pd.DataFrame({"timestamp": sample_times})
        res = add_calendar_features(df)

        # 00:00 -> sin = 0, cos = 1
        assert pytest.approx(res.loc[0, "hour_sin"], abs=1e-6) == 0.0
        assert pytest.approx(res.loc[0, "hour_cos"], abs=1e-6) == 1.0

        # 06:00 -> sin = 1, cos = 0
        assert pytest.approx(res.loc[1, "hour_sin"], abs=1e-6) == 1.0
        assert pytest.approx(res.loc[1, "hour_cos"], abs=1e-6) == 0.0

        # 12:00 -> sin = 0, cos = -1
        assert pytest.approx(res.loc[2, "hour_sin"], abs=1e-6) == 0.0
        assert pytest.approx(res.loc[2, "hour_cos"], abs=1e-6) == -1.0

        # Check sin^2 + cos^2 == 1
        for i in range(len(res)):
            norm_hour = res.loc[i, "hour_sin"] ** 2 + res.loc[i, "hour_cos"] ** 2
            assert pytest.approx(norm_hour, abs=1e-6) == 1.0

            norm_dow = res.loc[i, "day_of_week_sin"] ** 2 + res.loc[i, "day_of_week_cos"] ** 2
            assert pytest.approx(norm_dow, abs=1e-6) == 1.0

    def test_alert_lags(self):
        """Verifies that lags correspond to the exact past step counts."""
        df = _generate_synthetic_grid(days=2, seed=42)
        res = add_alert_lags(df)

        # 15m lag is shift(1)
        assert pd.isna(res.loc[0, "alert_lag_15m"])
        assert res.loc[1, "alert_lag_15m"] == df.loc[0, "is_alert"]
        assert res.loc[50, "alert_lag_15m"] == df.loc[49, "is_alert"]

        # 1h lag is shift(4)
        assert pd.isna(res.loc[3, "alert_lag_1h"])
        assert res.loc[4, "alert_lag_1h"] == df.loc[0, "is_alert"]
        assert res.loc[50, "alert_lag_1h"] == df.loc[46, "is_alert"]

        # 3h lag is shift(12)
        assert pd.isna(res.loc[11, "alert_lag_3h"])
        assert res.loc[12, "alert_lag_3h"] == df.loc[0, "is_alert"]

        # 6h lag is shift(24)
        assert pd.isna(res.loc[23, "alert_lag_6h"])
        assert res.loc[24, "alert_lag_6h"] == df.loc[0, "is_alert"]

        # 24h lag is shift(96)
        assert pd.isna(res.loc[95, "alert_lag_24h"])
        assert res.loc[96, "alert_lag_24h"] == df.loc[0, "is_alert"]

    def test_rolling_7d_duration_exclusion(self):
        """Verifies that the current row's duration is strictly excluded from rolling mean."""
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="15min"),
            "region_id": [1] * 5,
            "is_alert": [1, 1, 1, 1, 1],
            "alert_duration_minutes": [10.0, 20.0, 30.0, 40.0, 50.0],
        })

        res = add_rolling_alert_duration_7d(df, window_steps=3, min_periods=1)

        # Row 0: shifted is NaN, rolling mean must be NaN
        assert pd.isna(res.loc[0, "rolling_duration_mean_7d"])

        # Row 1: only row 0 (10.0) is visible -> mean is 10.0 (excludes row 1's 20.0!)
        assert res.loc[1, "rolling_duration_mean_7d"] == 10.0

        # Row 2: rows 0 and 1 are visible (10 + 20) / 2 = 15.0
        assert res.loc[2, "rolling_duration_mean_7d"] == 15.0

        # Row 3: rows 1 and 2 (window=3: rows 0, 1, 2) -> (10 + 20 + 30) / 3 = 20.0
        assert res.loc[3, "rolling_duration_mean_7d"] == 20.0

    def test_multi_region_partitioning(self):
        """Verifies that lags and rolling stats are computed independently per region."""
        df_r1 = _generate_synthetic_grid(days=2, region_id=1, seed=1)
        df_r2 = _generate_synthetic_grid(days=2, region_id=2, seed=2)
        df_combined = pd.concat([df_r1, df_r2], ignore_index=True)

        features = engineer_features(df_combined)

        # Compare with isolated computation
        features_r1_isolated = engineer_features(df_r1)
        features_r2_isolated = engineer_features(df_r2)

        slice_r1 = features[features["region_id"] == 1].reset_index(drop=True)
        slice_r2 = features[features["region_id"] == 2].reset_index(drop=True)

        cols_to_check = ["alert_lag_1h", "alert_lag_24h", "rolling_duration_mean_7d"]
        for col in cols_to_check:
            np.testing.assert_allclose(
                slice_r1[col].to_numpy(),
                features_r1_isolated[col].to_numpy(),
                equal_nan=True,
                err_msg=f"Region 1 features leaked or mismatch in '{col}'",
            )
            np.testing.assert_allclose(
                slice_r2[col].to_numpy(),
                features_r2_isolated[col].to_numpy(),
                equal_nan=True,
                err_msg=f"Region 2 features leaked or mismatch in '{col}'",
            )
