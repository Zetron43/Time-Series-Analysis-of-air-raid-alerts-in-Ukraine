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


def test_ai_agent_entrypoint_keyboards():
    """Verifies that map, region, and raion keyboards include one-click AI Agent access."""
    from src.bot.interactive_bot import (
        get_mapall_action_keyboard,
        get_raions_keyboard,
        get_raion_horizon_keyboard,
        get_forecast_action_keyboard,
    )

    # 1. Map keyboard has AI button
    map_kb = get_mapall_action_keyboard(horizon_code="15m")
    buttons = [btn["callback_data"] for row in map_kb["inline_keyboard"] for btn in row]
    assert "ai_map" in buttons

    # 2. Region horizon keyboard has AI button
    hor_kb = get_horizon_keyboard("sumy")
    hor_btns = [btn["callback_data"] for row in hor_kb["inline_keyboard"] for btn in row]
    assert "ai_reg_sumy" in hor_btns

    # 3. Raions list keyboard has AI button
    raions_kb = get_raions_keyboard("sumy")
    r_btns = [btn["callback_data"] for row in raions_kb["inline_keyboard"] for btn in row]
    assert "ai_reg_sumy" in r_btns

    # 4. Raion horizon keyboard has raion AI button
    raion_hor_kb = get_raion_horizon_keyboard("sumy", 0)
    rh_btns = [btn["callback_data"] for row in raion_hor_kb["inline_keyboard"] for btn in row]
    assert "ai_rn_sumy_0" in rh_btns

    # 5. Forecast action keyboards have AI buttons
    fc_raion = get_forecast_action_keyboard("sumy", 0, "15m")
    fc_raion_btns = [btn["callback_data"] for row in fc_raion["inline_keyboard"] for btn in row]
    assert "ai_rn_sumy_0" in fc_raion_btns

    fc_reg = get_forecast_action_keyboard("sumy", None, "15m")
    fc_reg_btns = [btn["callback_data"] for row in fc_reg["inline_keyboard"] for btn in row]
    assert "ai_reg_sumy" in fc_reg_btns



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


def test_raion_keyboards_and_callback_data_limits():
    """Ensures all raion callback data strings are strictly within Telegram's 64-byte limit."""
    from src.bot.interactive_bot import ALL_REGIONS, get_raions_keyboard, get_raion_horizon_keyboard

    for reg_code, meta in ALL_REGIONS.items():
        r_kb = get_raions_keyboard(reg_code)
        assert "inline_keyboard" in r_kb
        for row in r_kb["inline_keyboard"]:
            for btn in row:
                cb = btn["callback_data"]
                assert len(cb.encode("utf-8")) <= 64, f"Callback {cb} exceeds 64 bytes"

        raions = meta.get("raions", [])
        if raions:
            hrn_kb = get_raion_horizon_keyboard(reg_code, 0)
            assert "inline_keyboard" in hrn_kb
            for row in hrn_kb["inline_keyboard"]:
                for btn in row:
                    cb = btn["callback_data"]
                    assert len(cb.encode("utf-8")) <= 64, f"Callback {cb} exceeds 64 bytes"


def test_subscription_manager_flow(tmp_path):
    """Verifies adding, removing, and cooldown of raion subscriptions."""
    from src.bot.subscription_manager import UserSubscriptionManager
    test_file = str(tmp_path / "subs.json")
    mgr = UserSubscriptionManager(file_path=test_file)

    assert mgr.get_user_subscriptions(12345) == []
    added = mgr.add_subscription(12345, "Бучанський район")
    assert added is True
    assert mgr.get_user_subscriptions(12345) == ["Бучанський район"]

    # Re-adding does not duplicate
    added_again = mgr.add_subscription(12345, "Бучанський район")
    assert added_again is False
    assert len(mgr.get_user_subscriptions(12345)) == 1

    # Cooldown check
    assert mgr.should_notify(12345, "Бучанський район", "alarm_RED", cooldown_minutes=30) is True
    mgr.mark_notified(12345, "Бучанський район", "alarm_RED")
    assert mgr.should_notify(12345, "Бучанський район", "alarm_RED", cooldown_minutes=30) is False

    # Removal
    removed = mgr.remove_subscription(12345, "Бучанський район")
    assert removed is True
    assert mgr.get_user_subscriptions(12345) == []


def test_map_renderer_generates_valid_png():
    """Verifies that AlertMapRenderer creates a valid PNG byte stream."""
    from rendering.alert_map_renderer import AlertMapRenderer
    renderer = AlertMapRenderer()
    png_bytes = renderer.render_map(horizon_minutes=30, highlight_raion="Львівський район")

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 50000  # Detailed map with 137 raions is >50 KB
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")  # Standard PNG magic signature


def test_benchmark_metrics_summary():
    """Verifies that benchmark summary contains all 3 sources and Jaccard metrics."""
    from src.bot.interactive_bot import format_sources_benchmark_summary
    summary = format_sources_benchmark_summary()

    assert "alerts.in.ua" in summary
    assert "neptun.in.ua" in summary
    assert "dimap.live" in summary
    assert "Jaccard" in summary
    assert "%" in summary


def test_update_or_send_message_handles_photo_messages(monkeypatch):
    """Verifies that clicking buttons on photo messages deletes photo and falls back to sendMessage."""
    from src.bot import interactive_bot

    calls = []

    def mock_api_call(token, method, payload):
        calls.append((method, payload))
        if method == "editMessageText":
            return {"ok": False, "error_code": 400, "description": "Bad Request: there is no text in the message to edit"}
        return {"ok": True, "result": {"message_id": 999}}

    monkeypatch.setattr(interactive_bot, "telegram_api_call", mock_api_call)

    active_menu = {}

    # 1. When is_photo_message is True, should delete old photo and call sendMessage
    calls.clear()
    res1 = interactive_bot.update_or_send_message("fake_tok", 123, 456, "Hello", is_photo_message=True, user_active_menu=active_menu)
    assert res1.get("ok") is True
    assert len(calls) == 2
    assert calls[0] == ("deleteMessage", {"chat_id": 123, "message_id": 456})
    assert calls[1][0] == "sendMessage"
    assert active_menu["123"] == 999

    # 2. When is_photo_message is False but editMessageText fails with 'no text', deletes and falls back to sendMessage
    calls.clear()
    res2 = interactive_bot.update_or_send_message("fake_tok", 123, 456, "Hello", is_photo_message=False, user_active_menu=active_menu)
    assert res2.get("ok") is True
    assert len(calls) == 3
    assert calls[0][0] == "editMessageText"
    assert calls[1][0] == "deleteMessage"
    assert calls[2][0] == "sendMessage"
    assert active_menu["123"] == 999


def test_auto_delete_manager(tmp_path):
    """Verifies scheduling, popping, and 1-hour expiration handling of alarm messages."""
    from src.bot.subscription_manager import AutoDeleteManager
    test_file = str(tmp_path / "pending_deletions.json")
    mgr = AutoDeleteManager(file_path=test_file)

    # 1. Schedule message for deletion
    mgr.schedule_deletion(chat_id=123, message_id=555, delay_seconds=3600, raion_name="Львівський район")
    pending = mgr.get_pending()
    assert len(pending) == 1
    assert pending[0]["chat_id"] == 123
    assert pending[0]["message_id"] == 555
    assert pending[0]["raion_name"] == "Львівський район"

    # 2. Pop previous alerts for the same raion
    popped = mgr.pop_previous_raion_alerts(chat_id=123, raion_name="Львівський район")
    assert popped == [555]
    assert len(mgr.get_pending()) == 0

    # 3. Schedule two messages: one expired (delay=-10), one in future (delay=3600)
    mgr.schedule_deletion(chat_id=123, message_id=777, delay_seconds=-10, raion_name="Бучанський район")
    mgr.schedule_deletion(chat_id=123, message_id=888, delay_seconds=3600, raion_name="Бучанський район")

    deleted_api_calls = []
    def mock_caller(method, payload):
        deleted_api_calls.append((method, payload))
        return {"ok": True}

    count = mgr.process_pending(mock_caller)
    assert count == 1
    assert len(deleted_api_calls) == 1
    assert deleted_api_calls[0] == ("deleteMessage", {"chat_id": 123, "message_id": 777})

    # Only future message 888 remains
    remaining = mgr.get_pending()
    assert len(remaining) == 1
    assert remaining[0]["message_id"] == 888




