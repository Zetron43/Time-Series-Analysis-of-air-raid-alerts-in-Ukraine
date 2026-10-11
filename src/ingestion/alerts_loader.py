"""Loader and Resampler for Official Air Raid Alerts (alerts.in.ua & Official Dataset).

Transforms irregular interval events [started_at, finished_at, region]
into a causal regular 15-minute time grid.
"""

from pathlib import Path
from typing import Optional, Sequence
import os
import pandas as pd
import numpy as np


def load_official_alerts_csv(
    filepath: str = "data/alerts_official.csv",
    level: Optional[str] = None,
    target_oblast: Optional[str] = "Kyiv City",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Loads official air raid alert intervals from CSV.

    Args:
        filepath: Path to official_data_en.csv / official_data_uk.csv.
        level: Optional filter by level ('oblast', 'raion', 'hromada', or None for all).
        target_oblast: Specific oblast to filter (e.g. 'Kyiv City', 'Kyivska oblast').
        start_date: Optional lower bound (ISO format).
        end_date: Optional upper bound (ISO format).

    Returns:
        DataFrame with columns ['oblast', 'started_at', 'finished_at'].
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Alerts file not found at: {filepath}")

    df = pd.read_csv(
        path,
        usecols=["oblast", "level", "started_at", "finished_at"],
    )

    if level:
        df = df[df["level"] == level].copy()

    if target_oblast:
        df = df[df["oblast"] == target_oblast].copy()

    df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
    df["finished_at"] = pd.to_datetime(df["finished_at"], utc=True)

    # Filter out malformed intervals where finished_at < started_at
    valid_mask = df["finished_at"].isna() | (df["finished_at"] >= df["started_at"])
    df = df[valid_mask].copy()

    if start_date:
        df = df[df["started_at"] >= pd.to_datetime(start_date, utc=True)]
    if end_date:
        df = df[df["started_at"] <= pd.to_datetime(end_date, utc=True)]

    return df.sort_values(by="started_at").reset_index(drop=True)


def resample_alerts_to_grid(
    events_df: pd.DataFrame,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    grid_freq: str = "15min",
    region_name: str = "Kyivska oblast",
) -> pd.DataFrame:
    """Discretizes continuous event intervals [started_at, finished_at] into a regular 15-minute grid.

    Causal Invariants:
    - Point state `is_alert` is evaluated strictly at snapshot instant t_k:
      is_alert(t_k) = 1 if started_at <= t_k < finished_at else 0.
    - Interval duration `alert_duration_minutes` calculates overlap with past bin [t_{k-1}, t_k].
      Because the bin [t_{k-1}, t_k] has already concluded by time t_k, it introduces ZERO lookahead bias.

    Args:
        events_df: DataFrame containing ['started_at', 'finished_at'].
        start_dt: Start of regular grid.
        end_dt: End of regular grid.
        grid_freq: Grid step frequency (default: '15min').
        region_name: Region label.

    Returns:
        Regular DataFrame with ['timestamp', 'region_id', 'is_alert', 'alert_duration_minutes'].
    """
    timestamps = pd.date_range(start=start_dt, end=end_dt, freq=grid_freq, tz="UTC")
    n_points = len(timestamps)

    is_alert = np.zeros(n_points, dtype=int)
    durations = np.zeros(n_points, dtype=float)

    step_delta = pd.Timedelta(grid_freq)
    step_minutes = step_delta.total_seconds() / 60.0

    # Convert events to numpy arrays of timestamps for fast vectorization
    if not events_df.empty:
        ev_starts = events_df["started_at"].to_numpy(dtype="datetime64[ns]")
        ev_ends = events_df["finished_at"].fillna(pd.Timestamp.max.tz_localize("UTC")).to_numpy(dtype="datetime64[ns]")
        ts_arr = timestamps.to_numpy(dtype="datetime64[ns]")

        for s_j, e_j in zip(ev_starts, ev_ends):
            i_start = int(np.searchsorted(ts_arr, s_j, side="left"))
            i_end = int(np.searchsorted(ts_arr, e_j, side="left"))
            if i_start < n_points:
                is_alert[i_start : min(n_points, i_end)] = 1

            # Overlap duration with prior bin [t_{i-1}, t_i]
            idx_from = max(1, i_start)
            idx_to = min(n_points, i_end + 1)
            if idx_to > idx_from:
                t_prev = ts_arr[idx_from - 1 : idx_to - 1]
                t_curr = ts_arr[idx_from : idx_to]
                o_s = np.maximum(t_prev, s_j)
                o_e = np.minimum(t_curr, e_j)
                diff_ns = (o_e - o_s).astype("timedelta64[s]").astype(np.float64)
                valid = diff_ns > 0.0
                if np.any(valid):
                    durations[idx_from:idx_to] += np.where(valid, diff_ns / 60.0, 0.0)

        durations = np.minimum(step_minutes, durations)
        if is_alert[0]:
            durations[0] = step_minutes

    return pd.DataFrame({
        "timestamp": timestamps,
        "region_id": region_name,
        "is_alert": is_alert,
        "alert_duration_minutes": durations,
    })
