"""Unit tests for Telegram bot formatting and multi-channel OSINT ingestion."""

from datetime import datetime, timezone
import pytest
from src.bot.formatter import format_forecast_post, render_risk_bar, get_risk_badge
from src.ingestion.telegram_multi_channel import (
    extract_multi_channel_threats,
    join_multi_channel_features_to_grid,
)
import pandas as pd


def test_render_risk_bar():
    bar_low = render_risk_bar(0.10)
    assert "🟩" in bar_low
    assert "■" in bar_low

    bar_mid = render_risk_bar(0.25)
    assert "🟨" in bar_mid

    bar_high = render_risk_bar(0.80)
    assert "🟥" in bar_high


def test_format_forecast_post_quiet():
    dt = datetime(2026, 10, 10, 22, 0, 0, tzinfo=timezone.utc)
    signals = {"tg_shahed": 1, "tg_kyiv_targeted": 1}
    text = format_forecast_post(
        region_name="м. Київ",
        timestamp=dt,
        is_active=False,
        current_duration_min=0.0,
        prob_15m=0.35,
        prob_30m=0.45,
        prob_60m=0.60,
        osint_signals=signals,
    )

    assert "КИЇВ" in text.upper()
    assert "СПОКІЙНО" in text
    assert "35.0%" in text
    assert "Shahed" in text
    assert "вектор на регіон" in text


def test_format_forecast_post_active():
    dt = datetime(2026, 10, 10, 22, 15, 0, tzinfo=timezone.utc)
    signals = {"tg_ballistics": 1}
    text = format_forecast_post(
        region_name="м. Київ",
        timestamp=dt,
        is_active=True,
        current_duration_min=45.0,
        prob_15m=0.70,
        prob_30m=0.80,
        prob_60m=0.90,
        osint_signals=signals,
    )

    assert "ТРИВАЄ ТРИВОГА" in text
    assert "45 хв" in text
    assert "Балістична загроза" in text
