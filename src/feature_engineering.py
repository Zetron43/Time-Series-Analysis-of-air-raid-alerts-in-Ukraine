"""Feature Engineering Module for Air Raid Alerts Time Series.

Strict Zero-Leakage Policy:
- Every feature at time t_k is strictly a function of observations at t <= t_{k-1}
  (or for calendar features, deterministic functions of the timestamp t_k itself).
- All rolling aggregates use .shift(1) before .rolling() to ensure the current interval's
  realization is excluded from the feature set.
- Lags explicitly use positive step shifts (>= 1 step).
"""

from typing import Optional, Sequence
import numpy as np
import pandas as pd


# Constants for 15-minute discretized time grid
GRID_STEP_MINUTES: int = 15
STEPS_PER_HOUR: int = 60 // GRID_STEP_MINUTES  # 4 steps per hour

# Lag steps definitions
LAG_STEPS_MAP: dict[str, int] = {
    "15m": 1,
    "1h": 1 * STEPS_PER_HOUR,    # 4 steps
    "3h": 3 * STEPS_PER_HOUR,    # 12 steps
    "6h": 6 * STEPS_PER_HOUR,    # 24 steps
    "24h": 24 * STEPS_PER_HOUR,  # 96 steps
}

# 7-day rolling window step count
ROLLING_7D_STEPS: int = 7 * 24 * STEPS_PER_HOUR  # 672 steps


def add_calendar_features(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Add cyclic trigonometric calendar features (sin/cos transforms).

    Features are strictly deterministic functions of the cutoff timestamp t_k:
    - hour_sin, hour_cos: continuous cycle over 24 hours (including 15-min fractions).
    - day_of_week_sin, day_of_week_cos: cycle over 7 days of the week (0 = Monday, 6 = Sunday).

    Args:
        df: Input DataFrame containing the timestamp column.
        timestamp_col: Name of the timestamp column.

    Returns:
        DataFrame with added calendar features.
    """
    out = df.copy()
    ts = pd.to_datetime(out[timestamp_col])

    # Continuous hour in [0.0, 24.0) e.g. 14:15 -> 14.25
    hour_continuous = ts.dt.hour + ts.dt.minute / 60.0 + ts.dt.second / 3600.0
    out["hour_sin"] = np.sin(2.0 * np.pi * hour_continuous / 24.0)
    out["hour_cos"] = np.cos(2.0 * np.pi * hour_continuous / 24.0)

    # Day of week in [0, 6]
    dow = ts.dt.dayofweek
    out["day_of_week_sin"] = np.sin(2.0 * np.pi * dow / 7.0)
    out["day_of_week_cos"] = np.cos(2.0 * np.pi * dow / 7.0)

    return out


def add_alert_lags(
    df: pd.DataFrame,
    target_col: str = "is_alert",
    region_col: Optional[str] = "region_id",
    lags: Optional[dict[str, int]] = None,
) -> pd.DataFrame:
    """Add causal lag features of the alert state for previous hours.

    Uses shift(k) where k >= 1 step (15 min) to guarantee zero lookahead bias.
    If region_col is provided, lags are calculated per region partition.

    Args:
        df: Input DataFrame (must be chronologically sorted).
        target_col: Column indicating alert occurrence/state (e.g. 0 or 1).
        region_col: Optional column name for region grouping.
        lags: Dictionary of {feature_suffix: step_count}. Defaults to LAG_STEPS_MAP.

    Returns:
        DataFrame with added lag feature columns.
    """
    if lags is None:
        lags = LAG_STEPS_MAP

    out = df.copy()

    def _apply_lags(series: pd.Series) -> pd.DataFrame:
        lag_data = {}
        for name, steps in lags.items():
            col_name = f"alert_lag_{name}"
            # Causal shift: shift(steps) retrieves value from t_{k - steps}
            lag_data[col_name] = series.shift(steps)
        return pd.DataFrame(lag_data, index=series.index)

    if region_col is not None and region_col in out.columns:
        lag_dfs = [
            _apply_lags(group[target_col])
            for _, group in out.groupby(region_col, sort=False)
        ]
        lag_combined = pd.concat(lag_dfs).sort_index()
    else:
        lag_combined = _apply_lags(out[target_col])

    for col in lag_combined.columns:
        out[col] = lag_combined[col]

    return out


def add_rolling_alert_duration_7d(
    df: pd.DataFrame,
    duration_col: str = "alert_duration_minutes",
    region_col: Optional[str] = "region_id",
    window_steps: int = ROLLING_7D_STEPS,
    min_periods: int = 1,
) -> pd.DataFrame:
    """Add causal rolling average of alert duration over the last 7 days.

    Causal Invariant:
    At timestamp t_k, the rolling average is computed over:
        [t_{k - window}, t_{k - 1}]
    The current interval's duration at t_k is strictly excluded by applying
    `.shift(1)` BEFORE the rolling window calculation.

    Args:
        df: Input DataFrame (must be chronologically sorted).
        duration_col: Column containing alert duration in minutes for each 15-min interval.
        region_col: Optional column name for region grouping.
        window_steps: Number of steps for 7 days (default: 672 for 15-min grid).
        min_periods: Minimum observations required in window (default: 1).

    Returns:
        DataFrame with added 'rolling_duration_mean_7d' column.
    """
    out = df.copy()

    def _apply_rolling(series: pd.Series) -> pd.Series:
        # Step 1: Shift by 1 to exclude current observation t_k
        shifted = series.shift(1)
        # Step 2: Compute rolling mean over past window
        return shifted.rolling(window=window_steps, min_periods=min_periods).mean()

    feature_col_name = "rolling_duration_mean_7d"

    if region_col is not None and region_col in out.columns:
        rolling_series = (
            out.groupby(region_col, sort=False)[duration_col]
            .apply(_apply_rolling)
            .reset_index(level=0, drop=True)
            .sort_index()
        )
    else:
        rolling_series = _apply_rolling(out[duration_col])

    out[feature_col_name] = rolling_series
    return out


def engineer_features(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    alert_col: str = "is_alert",
    duration_col: str = "alert_duration_minutes",
    region_col: Optional[str] = "region_id",
    min_periods_7d: int = 1,
) -> pd.DataFrame:
    """End-to-end causal feature engineering pipeline for 15-min air raid time grid.

    Generates:
    1. Calendar cyclic features:
       - hour_sin, hour_cos (continuous 24h cycle)
       - day_of_week_sin, day_of_week_cos (7d cycle)
    2. Alert lags:
       - alert_lag_15m (1 step)
       - alert_lag_1h (4 steps)
       - alert_lag_3h (12 steps)
       - alert_lag_6h (24 steps)
       - alert_lag_24h (96 steps)
    3. Causal rolling stats:
       - rolling_duration_mean_7d (7-day window with shift(1))

    Args:
        df: Input DataFrame containing 15-min regular grid.
        timestamp_col: Name of timestamp column.
        alert_col: Name of binary alert state column (0/1).
        duration_col: Name of interval alert duration column (minutes in interval).
        region_col: Optional region identifier for grouping.
        min_periods_7d: Minimum periods for 7d rolling average.

    Returns:
        DataFrame with all engineered features appended.
    """
    # Verify required columns
    required_cols = [timestamp_col, alert_col]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Required column '{col}' missing from DataFrame.")

    # If duration_col is missing, derive from alert_col (assuming 15 mins if alert is active)
    out = df.copy()
    if duration_col not in out.columns:
        out[duration_col] = out[alert_col].astype(float) * float(GRID_STEP_MINUTES)

    # Ensure chronological order
    sort_cols = [region_col, timestamp_col] if (region_col and region_col in out.columns) else [timestamp_col]
    out = out.sort_values(by=sort_cols).reset_index(drop=True)

    # 1. Calendar features
    out = add_calendar_features(out, timestamp_col=timestamp_col)

    # 2. Alert lags
    out = add_alert_lags(
        out,
        target_col=alert_col,
        region_col=region_col,
        lags=LAG_STEPS_MAP,
    )

    # 3. 7-day rolling average duration
    out = add_rolling_alert_duration_7d(
        out,
        duration_col=duration_col,
        region_col=region_col,
        window_steps=ROLLING_7D_STEPS,
        min_periods=min_periods_7d,
    )

    return out
