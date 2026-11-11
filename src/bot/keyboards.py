"""Telegram Inline Keyboard Builders for Air Raid Alerts Bot.

Extracts UI button construction from interactive_bot into a dedicated, testable module.
"""

import os
import urllib.parse
from typing import Dict, Any, List, Optional

from src.bot.subscription_manager import UserSubscriptionManager


def get_macro_zones_keyboard(
    chat_id: Optional[int | str] = None,
    sub_manager: Optional[UserSubscriptionManager] = None,
) -> dict:
    """Builds Telegram Inline Keyboard for Macro-Zones selection with Home Raion & WebApp."""
    keyboard = []

    # 1. Pinned Home Raion Button (if user configured one)
    if chat_id and sub_manager:
        home_meta = sub_manager.get_home_raion(chat_id)
        if home_meta and home_meta.get("raion"):
            r_name = home_meta["raion"]
            lvl_badge = "🟢"
            try:
                from src.bot.threat_state_manager import get_threat_syncer
                st = get_threat_syncer().get_raion_status(r_name)
                lvl_badge = "🔴" if st.get("level") == "RED" else ("🟡" if st.get("level") == "YELLOW" else "🟢")
            except Exception:
                pass
            keyboard.append([
                {"text": f"⭐ Мій район: {r_name} ({lvl_badge})", "callback_data": "quick_home"},
            ])

    # 2. Interactive WebApp Button
    webapp_url = os.environ.get("WEBAPP_URL") or os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if webapp_url:
        webapp_url = webapp_url.strip()
        if not webapp_url.startswith("http://") and not webapp_url.startswith("https://"):
            webapp_url = f"https://{webapp_url}"
        sep = "&" if "?" in webapp_url else "?"
        user_url = f"{webapp_url}{sep}chat_id={chat_id}" if chat_id else webapp_url
        keyboard.append([
            {"text": "📱 Відкрити живу інтерактивну мапу", "web_app": {"url": user_url}},
        ])

    keyboard.extend([
        [
            {"text": "🏙 Столиця та Північ", "callback_data": "zone_north"},
            {"text": "🧭 Схід України", "callback_data": "zone_east"},
        ],
        [
            {"text": "🧭 Центр України", "callback_data": "zone_center"},
            {"text": "🧭 Південь України", "callback_data": "zone_south"},
        ],
        [
            {"text": "🧭 Захід України", "callback_data": "zone_west"},
            {"text": "🗺 Усі області (А-Я)", "callback_data": "zone_all"},
        ],
        [
            {"text": "🗺 Карта тривог України", "callback_data": "mapall_kyiv_15m"},
            {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        ],
    ])
    return {"inline_keyboard": keyboard}


def get_zone_regions_keyboard(zone_key: str) -> dict:
    """Builds Telegram Inline Keyboard for regions within a macro-zone."""
    from src.bot.interactive_bot import MACRO_ZONES, ALL_REGIONS
    zone_data = MACRO_ZONES.get(zone_key)
    keyboard = []
    if zone_data:
        codes = zone_data["codes"]
        for i in range(0, len(codes), 2):
            row = []
            for c in codes[i : i + 2]:
                row.append({"text": f"📍 {ALL_REGIONS[c]['name']}", "callback_data": f"reg_{c}"})
            keyboard.append(row)
    keyboard.append([
        {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        {"text": "⬅️ Назад до макрорегіонів", "callback_data": "menu_zones"},
    ])
    return {"inline_keyboard": keyboard}


def get_all_regions_keyboard() -> dict:
    """Builds Telegram Inline Keyboard listing all 26 regions alphabetically."""
    from src.bot.interactive_bot import ALL_REGIONS
    keyboard = []
    codes = list(ALL_REGIONS.keys())
    codes.sort(key=lambda c: ALL_REGIONS[c]["name"])
    for i in range(0, len(codes), 2):
        row = []
        for c in codes[i : i + 2]:
            row.append({"text": f"📍 {ALL_REGIONS[c]['name']}", "callback_data": f"reg_{c}"})
        keyboard.append(row)
    keyboard.append([
        {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        {"text": "⬅️ Назад до макрорегіонів", "callback_data": "menu_zones"},
    ])
    return {"inline_keyboard": keyboard}


def get_region_keyboard() -> dict:
    """Primary entry point returning macro-zones keyboard."""
    return get_macro_zones_keyboard()


def get_horizon_keyboard(region_code: str) -> dict:
    """Builds Telegram Inline Keyboard for whole-region horizon selection."""
    from src.bot.interactive_bot import ALL_REGIONS
    reg_meta = ALL_REGIONS.get(region_code, {"zone": "zone_north"})
    zone_code = reg_meta.get("zone", "zone_north")

    keyboard = [
        [
            {"text": "⏱ 15 хвилин", "callback_data": f"hor_{region_code}_15m"},
            {"text": "⏱ 30 хвилин", "callback_data": f"hor_{region_code}_30m"},
        ],
        [
            {"text": "⏱ 1 година", "callback_data": f"hor_{region_code}_1h"},
            {"text": "⏱ 2 години", "callback_data": f"hor_{region_code}_2h"},
        ],
        [
            {"text": "🔔 Слідкувати за всією областю", "callback_data": f"subreg_{region_code}"},
            {"text": "🤖 Запитати ШІ про область", "callback_data": f"ai_reg_{region_code}"},
        ],
        [
            {"text": "🗺 Карта загроз (з БпЛА)", "callback_data": f"mapall_{region_code}_15m"},
            {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        ],
        [
            {"text": "🏘 Обрати конкретний район", "callback_data": f"reg_{region_code}"},
            {"text": "⬅️ Назад до вибору області", "callback_data": zone_code},
        ],
        [
            {"text": "📍 Усі регіони", "callback_data": "menu_zones"},
        ],
    ]
    return {"inline_keyboard": keyboard}


def get_raions_keyboard(region_code: str, raions_status_map: Optional[Dict[str, Dict[str, Any]]] = None) -> dict:
    """Builds Telegram Inline Keyboard for choosing a specific raion in the region.

    Displays independent real-time status emoji (🔴 official alert, 🟡 warning, 🟢 clear) for each raion.
    """
    from src.bot.interactive_bot import ALL_REGIONS
    reg_meta = ALL_REGIONS.get(region_code, {})
    raions = reg_meta.get("raions", [])
    zone_code = reg_meta.get("zone", "zone_north")

    if raions_status_map is None:
        try:
            from src.ingestion.alerts_live_client import AlertsInUaLiveClient
            client = AlertsInUaLiveClient()
            reg_status = client.get_region_status(
                reg_meta.get("keys", []),
                reg_meta.get("name", region_code),
                raion_names=raions,
            )
            raions_status_map = {r["name"]: r for r in reg_status.get("raions", [])}
        except Exception:
            raions_status_map = {}

    keyboard = []
    for i in range(0, len(raions), 2):
        row = []
        for idx in range(i, min(i + 2, len(raions))):
            r_name = raions[idx]
            short_name = r_name.replace(" район", "").strip()
            r_info = raions_status_map.get(r_name, {}) if raions_status_map else {}
            badge = r_info.get("badge", "🟢") if r_info else "🟢"
            row.append({
                "text": f"{badge} {short_name}",
                "callback_data": f"rn_{region_code}_{idx}",
            })
        keyboard.append(row)

    keyboard.append([
        {"text": "🔔 Слідкувати за всією областю", "callback_data": f"subreg_{region_code}"},
        {"text": "🌐 Вся область (зведення)", "callback_data": f"regall_{region_code}"},
    ])
    keyboard.append([
        {"text": "🤖 Запитати ШІ про область", "callback_data": f"ai_reg_{region_code}"},
        {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
    ])
    keyboard.append([
        {"text": "🗺 Карта загроз (з БпЛА)", "callback_data": f"mapall_{region_code}_15m"},
        {"text": "⬅️ Назад до областей", "callback_data": zone_code},
    ])
    keyboard.append([
        {"text": "📍 Усі регіони", "callback_data": "menu_zones"},
    ])
    return {"inline_keyboard": keyboard}


def get_raion_horizon_keyboard(region_code: str, raion_idx: int, chat_id: Optional[int | str] = None) -> dict:
    """Builds Telegram Inline Keyboard for horizon selection for a specific raion."""
    from src.bot.interactive_bot import ALL_REGIONS
    reg_meta = ALL_REGIONS.get(region_code, {})
    raions = reg_meta.get("raions", [])
    raion_name = raions[raion_idx] if 0 <= raion_idx < len(raions) else None

    keyboard = []

    # Two-way sync: Bot Message -> WebApp focused on this raion with chat_id
    webapp_url = os.environ.get("WEBAPP_URL") or os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if webapp_url and raion_name:
        webapp_url = webapp_url.strip()
        if not webapp_url.startswith("http://") and not webapp_url.startswith("https://"):
            webapp_url = f"https://{webapp_url}"
        sep = "&" if "?" in webapp_url else "?"
        app_raion_url = f"{webapp_url}{sep}raion={urllib.parse.quote(raion_name)}"
        if chat_id:
            app_raion_url += f"&chat_id={chat_id}"
        keyboard.append([
            {"text": f"🗺 Відкрити «{raion_name}» на мапі", "web_app": {"url": app_raion_url}},
        ])

    keyboard.extend([
        [
            {"text": "⏱ 15 хвилин", "callback_data": f"hrn_{region_code}_{raion_idx}_15m"},
            {"text": "⏱ 30 хвилин", "callback_data": f"hrn_{region_code}_{raion_idx}_30m"},
        ],
        [
            {"text": "⏱ 1 година", "callback_data": f"hrn_{region_code}_{raion_idx}_1h"},
            {"text": "⏱ 2 години", "callback_data": f"hrn_{region_code}_{raion_idx}_2h"},
        ],
        [
            {"text": "🤖 Запитати ШІ про цей район", "callback_data": f"ai_rn_{region_code}_{raion_idx}"},
            {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        ],
        [
            {"text": "🗺 Статична карта (з БпЛА)", "callback_data": f"map_{region_code}_{raion_idx}_15m"},
            {"text": "⭐ Зробити моїм районом", "callback_data": f"sethome_{region_code}_{raion_idx}"},
        ],
        [
            {"text": "🔔 Слідкувати за районом", "callback_data": f"subadd_{region_code}_{raion_idx}"},
            {"text": "⬅️ Назад до районів", "callback_data": f"reg_{region_code}"},
        ],
    ])
    return {"inline_keyboard": keyboard}


def get_forecast_action_keyboard(
    region_code: str,
    raion_idx: Optional[int],
    horizon_code: str,
    chat_id: Optional[int | str] = None,
) -> dict:
    """Builds action keyboard under the generated forecast."""
    from src.bot.interactive_bot import ALL_REGIONS
    webapp_url = os.environ.get("WEBAPP_URL") or os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if webapp_url:
        webapp_url = webapp_url.strip()
        if not webapp_url.startswith("http://") and not webapp_url.startswith("https://"):
            webapp_url = f"https://{webapp_url}"

    if raion_idx is not None:
        reg_meta = ALL_REGIONS.get(region_code, {})
        raions = reg_meta.get("raions", [])
        raion_name = raions[raion_idx] if 0 <= raion_idx < len(raions) else None

        keyboard = []
        if webapp_url and raion_name:
            sep = "&" if "?" in webapp_url else "?"
            app_raion_url = f"{webapp_url}{sep}raion={urllib.parse.quote(raion_name)}"
            if chat_id:
                app_raion_url += f"&chat_id={chat_id}"
            keyboard.append([
                {"text": f"🗺 Відкрити «{raion_name}» на мапі", "web_app": {"url": app_raion_url}},
            ])

        keyboard.extend([
            [
                {"text": "🔄 Оновити прогноз", "callback_data": f"hrn_{region_code}_{raion_idx}_{horizon_code}"},
                {"text": "🤖 ШІ-Оцінка району", "callback_data": f"ai_rn_{region_code}_{raion_idx}"},
            ],
            [
                {"text": "🗺 Статична карта (з БпЛА)", "callback_data": f"map_{region_code}_{raion_idx}_{horizon_code}"},
                {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
            ],
            [
                {"text": "⭐ Зробити моїм районом", "callback_data": f"sethome_{region_code}_{raion_idx}"},
                {"text": "🔔 Слідкувати за районом", "callback_data": f"subadd_{region_code}_{raion_idx}"},
            ],
            [
                {"text": "⏱ Інший час", "callback_data": f"rn_{region_code}_{raion_idx}"},
                {"text": "📍 Змінити область", "callback_data": "menu_zones"},
            ],
        ])
    else:
        keyboard = []
        if webapp_url:
            sep = "&" if "?" in webapp_url else "?"
            user_app_url = f"{webapp_url}{sep}chat_id={chat_id}" if chat_id else webapp_url
            keyboard.append([
                {"text": "📱 Відкрити живу мапу України", "web_app": {"url": user_app_url}},
            ])
        keyboard.extend([
            [
                {"text": "🔄 Оновити прогноз", "callback_data": f"hor_{region_code}_{horizon_code}"},
                {"text": "🤖 ШІ-Оцінка області", "callback_data": f"ai_reg_{region_code}"},
            ],
            [
                {"text": "🗺 Статична карта (з БпЛА)", "callback_data": f"mapall_{region_code}_{horizon_code}"},
                {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
            ],
            [
                {"text": "🏘 Обрати конкретний район", "callback_data": f"reg_{region_code}"},
                {"text": "⏱ Інший час", "callback_data": f"regall_{region_code}"},
            ],
            [
                {"text": "📍 Змінити область", "callback_data": "menu_zones"},
            ],
        ])
    return {"inline_keyboard": keyboard}


def get_mapall_action_keyboard(region_code: str = "kyiv", horizon_code: str = "15m") -> dict:
    """Builds interactive action keyboard under the all-Ukraine radar threat map."""
    def h_btn(code: str, label: str) -> dict:
        prefix = "🔘 " if code == horizon_code else "⏱ "
        return {"text": f"{prefix}{label}", "callback_data": f"mapall_{region_code}_{code}"}

    keyboard = [
        [
            {"text": "🔄 Оновити карту", "callback_data": f"mapall_{region_code}_{horizon_code}"},
            {"text": "🤖 ШІ-Огляд загроз в Україні", "callback_data": "ai_map"},
        ],
        [
            h_btn("15m", "15 хв"),
            h_btn("30m", "30 хв"),
            h_btn("1h", "1 год"),
            h_btn("2h", "2 год"),
        ],
        [
            {"text": "📍 Меню областей", "callback_data": "menu_zones"},
            {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
        ],
        [
            {"text": "🔔 Мої підписки", "callback_data": "menu_tracking"},
        ],
    ]
    return {"inline_keyboard": keyboard}


def get_tracking_menu_keyboard(chat_id: int | str, sub_manager: UserSubscriptionManager) -> dict:
    """Builds inline keyboard for managing user subscriptions."""
    subs = sub_manager.get_user_subscriptions(chat_id)
    keyboard = []
    for idx, r_name in enumerate(subs):
        keyboard.append([
            {"text": f"❌ Відписатись: {r_name}", "callback_data": f"subdel_{idx}"}
        ])
    keyboard.append([
        {"text": "➕ Додати район (обрати область)", "callback_data": "menu_zones"},
    ])
    keyboard.append([
        {"text": "🗺 Карта тривог України", "callback_data": "mapall_kyiv_15m"},
        {"text": "📊 Метрики джерел", "callback_data": "menu_metrics"},
    ])
    keyboard.append([
        {"text": "⬅️ Меню регіонів", "callback_data": "menu_zones"},
    ])
    return {"inline_keyboard": keyboard}
