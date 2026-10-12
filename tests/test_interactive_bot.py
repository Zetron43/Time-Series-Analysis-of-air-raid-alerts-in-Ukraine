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


def test_single_drone_west_probability_decay():
    """Verifies that 1 single drone in Western regions has very low continuation prob at 2 hours (<10%)."""
    from src.bot.interactive_bot import compute_dynamic_operational_probability

    live_status = {"is_alert": True, "alert_level": "YELLOW"}
    threats_single = {
        "shahed": {"active": True, "scale_type": "single"},
        "ballistics": {"active": False},
        "mig31": {"active": False},
    }

    p_15m, expl_15m = compute_dynamic_operational_probability("lviv", 15, live_status, threats_single)
    p_30m, expl_30m = compute_dynamic_operational_probability("lviv", 30, live_status, threats_single)
    p_1h, expl_1h = compute_dynamic_operational_probability("lviv", 60, live_status, threats_single)
    p_2h, expl_2h = compute_dynamic_operational_probability("lviv", 120, live_status, threats_single)

    # In Western region for single drone:
    assert p_15m >= 0.55
    assert p_30m < 0.40
    assert p_1h < 0.20
    assert p_2h <= 0.10  # Must be <= 10%, NOT 73%!
    assert "поодинокий" in expl_2h.lower() or "1 дрон" in expl_2h.lower()


def test_group_drone_probability_higher_than_single():
    """Verifies that group of drones produces higher probability across horizons than 1 drone."""
    from src.bot.interactive_bot import compute_dynamic_operational_probability

    live_status = {"is_alert": True, "alert_level": "YELLOW"}
    threats_single = {"shahed": {"active": True, "scale_type": "single"}}
    threats_group = {"shahed": {"active": True, "scale_type": "group"}}

    p_single_2h, _ = compute_dynamic_operational_probability("lviv", 120, live_status, threats_single)
    p_group_2h, expl_group = compute_dynamic_operational_probability("lviv", 120, live_status, threats_group)

    assert p_group_2h > p_single_2h
    assert p_group_2h >= 0.20
    assert "групу" in expl_group.lower() or "хвилю" in expl_group.lower()


def test_drone_regex_patterns():
    """Verifies that regex correctly identifies single vs group drone keywords."""
    from src.ingestion.alerts_live_client import SINGLE_DRONE_PATTERNS, GROUP_DRONE_PATTERNS

    single_samples = [
        "1х БпЛА повз Стрий курсом на Львівщину",
        "Поодинокий БпЛА у напрямку Луцька",
        "Одиночний дрон над Тернопільщиною",
        "Останній дрон курсом на захід",
    ]
    for s in single_samples:
        assert any(p.search(s) for p in SINGLE_DRONE_PATTERNS)

    group_samples = [
        "Група БпЛА на Хмельниччині курсом на Тернопіль",
        "Декілька груп БпЛА курсом на західні області",
        "3х БпЛА в напрямку Франківська",
        "Масована атака дронів",
    ]
    for g in group_samples:
        assert any(p.search(g) for p in GROUP_DRONE_PATTERNS)

