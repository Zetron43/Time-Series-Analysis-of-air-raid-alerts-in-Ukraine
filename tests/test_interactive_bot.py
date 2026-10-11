"""Tests for Interactive Bot and Threat Classification Logic."""

import pytest
from src.bot.interactive_bot import (
    AVAILABLE_REGIONS,
    AVAILABLE_HORIZONS,
    ThreatAnalyzer,
    format_interactive_forecast_response,
    get_region_keyboard,
    get_horizon_keyboard,
)


def test_region_and_horizon_keyboards():
    reg_kb = get_region_keyboard()
    assert "inline_keyboard" in reg_kb
    assert len(reg_kb["inline_keyboard"]) >= 3

    # Check that region callback data starts with 'zone_'
    first_btn = reg_kb["inline_keyboard"][0][0]
    assert first_btn["callback_data"].startswith("zone_")

    hor_kb = get_horizon_keyboard("kharkiv")
    assert "inline_keyboard" in hor_kb
    first_hor_btn = hor_kb["inline_keyboard"][0][0]
    assert first_hor_btn["callback_data"].startswith("hor_kharkiv_")


def test_threat_analyzer_output_structure():
    analyzer = ThreatAnalyzer()
    res = analyzer.analyze_threats_for_region("kyiv", "30m")

    assert res["region_code"] == "kyiv"
    assert res["region_name"] == "м. Київ"
    assert res["horizon_minutes"] == 30
    assert 0.0 <= res["overall_probability"] <= 1.0

    threats = res["threats"]
    for t_type in ["shahed", "ballistics", "aviation", "mig31", "missile"]:
        assert t_type in threats
        assert "desc" in threats[t_type]
        assert "prob" in threats[t_type]
        assert "active" in threats[t_type]


def test_formatted_response_content():
    analyzer = ThreatAnalyzer()
    res = analyzer.analyze_threats_for_region("odesa", "1h")
    msg = format_interactive_forecast_response(res)

    assert "Одеська область" in msg
    assert "1 година" in msg
    assert "Ймовірність" in msg
    assert "Ударні дрони (Shahed)" in msg
    assert "Балістичні ракети" in msg
    assert "Тактична авіація (КАБ)" in msg
    assert "МіГ-31К" in msg
    assert "Крилаті ракети" in msg


def test_all_26_regions_present():
    from src.bot.interactive_bot import ALL_REGIONS, get_all_regions_keyboard
    assert len(ALL_REGIONS) == 26

    kb = get_all_regions_keyboard()
    # 26 regions arranged in 2 columns = 13 rows + 1 back button row = 14 rows
    assert len(kb["inline_keyboard"]) == 14

    for code, reg in ALL_REGIONS.items():
        assert "name" in reg
        assert "keys" in reg
        assert "raions" in reg
        assert len(reg["raions"]) >= 3


def test_crimea_nominal_status():
    from src.bot.interactive_bot import ThreatAnalyzer, format_region_selection_overview
    analyzer = ThreatAnalyzer()
    res = analyzer.analyze_threats_for_region("crimea", "1h")

    assert res["region_code"] == "crimea"
    assert res["live_status"]["is_alert"] is True
    assert res["live_status"]["alert_level"] == "NOMINAL"
    assert "НОМІНАЛЬНА ТРИВОГА" in res["live_status"]["badge"]
    assert len(res["live_status"]["raions"]) >= 10

    overview = format_region_selection_overview("crimea")
    assert "АР КРИМ" in overview
    assert "НОМІНАЛЬНА ТРИВОГА" in overview
    assert "Сімферопольський район" in overview
    assert "Севастополь" in overview


def test_raions_breakdown_included():
    from src.bot.interactive_bot import ThreatAnalyzer, format_interactive_forecast_response
    analyzer = ThreatAnalyzer()
    res = analyzer.analyze_threats_for_region("sumy", "1h")

    raions = res["live_status"].get("raions", [])
    assert len(raions) == 5
    for r in raions:
        assert "name" in r
        assert "status" in r
        assert "badge" in r
        assert r["badge"] in ["🔴", "🟡", "🟠", "🟢"]

    msg = format_interactive_forecast_response(res)
    assert "СТАН ПО ВСІХ РАЙОНАХ" in msg
    assert "Конотопський район" in msg
    assert "Сумський район" in msg
    assert "Охтирський район" in msg
