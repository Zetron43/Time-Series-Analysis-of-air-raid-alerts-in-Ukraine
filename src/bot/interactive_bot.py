"""Interactive Telegram Bot for Region & Horizon Selection with Live Threat Identification.

Real-Time Features:
1. Live integration with alerts.in.ua (SITREP feed) & official Air Force (@kpszsu) + War Monitor (@war_monitor).
2. Live Alert Level Categorization:
   - 🔴 Red: Missile danger / mass strike / ballistics (Seek shelter immediately!)
   - 🟡 Yellow: Drone danger / heightened alert (UAV activity)
   - 🟠 Artillery: Artillery / MLRS shelling threat in border/frontline sectors
   - 🟣 Partial: Regional alarms in specific raions / hromadas
   - 🟢 Clear: No active alarm in region
3. Full coverage of all 26 Ukrainian regions grouped into intuitive macro-zones.
4. Exact Europe/Kyiv local time with second-accurate live updates and horizon targets.
5. Specific approaching threat breakdown (Drones, Ballistics, CABs, MiG-31K, Cruise Missiles).
6. Long Polling Handler for Inline Keyboards & Callback Queries.
7. Interactive CLI Simulation mode for instant verification.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

from src.ingestion.alerts_live_client import AlertsInUaLiveClient, KYIV_TZ
from src.ingestion.telegram_multi_channel import (
    fetch_all_monitoring_channels,
    extract_multi_channel_threats,
)


# Complete Catalog of all 26 Ukrainian Regions with Official Administrative Raions
ALL_REGIONS = {
    # Столиця та Північ
    "kyiv": {
        "name": "м. Київ",
        "zone": "zone_north",
        "keys": ["м. київ", "m. kyiv", "київ (місто)", "київ"],
        "raions": [
            "Деснянський район",
            "Дніпровський район",
            "Дарницький район",
            "Оболонський район",
            "Подільський район",
            "Шевченківський район",
            "Печерський район",
            "Солом'янський район",
            "Святошинський район",
            "Голосіївський район",
        ],
    },
    "kyiv_obl": {
        "name": "Київська область",
        "zone": "zone_north",
        "keys": ["київська область", "kyivska oblast", "київщин", "біла церква", "бровар", "бориспіль", "фастів", "обухів", "бучан"],
        "raions": [
            "Білоцерківський район",
            "Бориспільський район",
            "Броварський район",
            "Бучанський район",
            "Вишгородський район",
            "Обухівський район",
            "Фастівський район",
        ],
    },
    "chernihiv": {
        "name": "Чернігівська область",
        "zone": "zone_north",
        "keys": ["чернігівська", "chernihivska", "чернігів", "ніжин", "прилуки", "корхів"],
        "raions": [
            "Корюківський район",
            "Ніжинський район",
            "Новгород-Сіверський район",
            "Прилуцький район",
            "Чернігівський район",
        ],
    },
    "sumy": {
        "name": "Сумська область",
        "zone": "zone_north",
        "keys": ["сумська", "sumska", "суми", "конотоп", "шостка", "охтирка", "ромен", "глухів"],
        "raions": [
            "Конотопський район",
            "Охтирський район",
            "Роменський район",
            "Сумський район",
            "Шосткинський район",
        ],
    },
    "zhytomyr": {
        "name": "Житомирська область",
        "zone": "zone_north",
        "keys": ["житомирська", "zhytomyrska", "житомир", "коростень", "звягель", "бердичів"],
        "raions": [
            "Бердичівський район",
            "Житомирський район",
            "Коростенський район",
            "Звягельський район",
        ],
    },

    # Схід
    "kharkiv": {
        "name": "Харківська область",
        "zone": "zone_east",
        "keys": ["харківська", "kharkivska", "харків", "чугуїв", "куп'янськ", "богодухів", "ізюм", "лозова"],
        "raions": [
            "Богодухівський район",
            "Ізюмський район",
            "Красноградський (Берестинський) район",
            "Куп'янський район",
            "Лозівський район",
            "Харківський район",
            "Чугуївський район",
        ],
    },
    "donetsk": {
        "name": "Донецька область",
        "zone": "zone_east",
        "keys": ["донецька", "donetska", "краматорськ", "слов'янськ", "покровськ", "бахмут"],
        "raions": [
            "Бахмутський район",
            "Волноваський район",
            "Горлівський район",
            "Донецький район",
            "Кальміуський район",
            "Краматорський район",
            "Маріупольський район",
            "Покровський район",
        ],
    },
    "luhansk": {
        "name": "Луганська область",
        "zone": "zone_east",
        "keys": ["луганська", "luhanska", "луганськ", "сіверськодонецьк"],
        "raions": [
            "Алчевський район",
            "Довжанський район",
            "Луганський район",
            "Ровеньківський район",
            "Сватівський район",
            "Сєвєродонецький район",
            "Старобільський район",
            "Щастинський район",
        ],
    },

    # Центр
    "dnipro": {
        "name": "Дніпропетровська область",
        "zone": "zone_center",
        "keys": ["дніпропетровська", "dnipropetrovska", "дніпро", "кривий ріг", "нікополь", "павлоград", "кам'янське", "марганець"],
        "raions": [
            "Дніпровський район",
            "Кам'янський район",
            "Криворізький район",
            "Нікопольський район",
            "Новомосковський (Самарівський) район",
            "Павлоградський район",
            "Синельниківський район",
        ],
    },
    "poltava": {
        "name": "Полтавська область",
        "zone": "zone_center",
        "keys": ["полтавська", "poltavska", "полтава", "кременчук", "миргород", "лубни"],
        "raions": [
            "Кременчуцький район",
            "Лубенський район",
            "Миргородський район",
            "Полтавський район",
        ],
    },
    "cherkasy": {
        "name": "Черкаська область",
        "zone": "zone_center",
        "keys": ["черкаська", "cherkaska", "черкаси", "умань", "сміла", "золотоноша"],
        "raions": [
            "Звенигородський район",
            "Золотоніський район",
            "Уманський район",
            "Черкаський район",
        ],
    },
    "kirovohrad": {
        "name": "Кіровоградська область",
        "zone": "zone_center",
        "keys": ["кіровоградська", "kirovohradska", "кропивницький", "олександрія", "знам'янка", "світловодськ"],
        "raions": [
            "Голованівський район",
            "Кропивницький район",
            "Новоукраїнський район",
            "Олександрійський район",
        ],
    },
    "vinnytsia": {
        "name": "Вінницька область",
        "zone": "zone_center",
        "keys": ["вінницька", "vinnytska", "вінниця", "жмеринка", "могилів-подільський", "гайсин"],
        "raions": [
            "Вінницький район",
            "Гайсинський район",
            "Жмеринський район",
            "Могилів-Подільський район",
            "Тульчинський район",
            "Хмільницький район",
        ],
    },

    # Південь
    "odesa": {
        "name": "Одеська область",
        "zone": "zone_south",
        "keys": ["одеська", "odeska", "одеса", "чорноморськ", "ізмаїл", "білгород-дністровський", "затока"],
        "raions": [
            "Березівський район",
            "Білгород-Дністровський район",
            "Болградський район",
            "Ізмаїльський район",
            "Одеський район",
            "Подільський район",
            "Роздільнянський район",
        ],
    },
    "mykolaiv": {
        "name": "Миколаївська область",
        "zone": "zone_south",
        "keys": ["миколаївська", "mykolaivska", "миколаїв", "очаків", "вознесенськ", "баштанка"],
        "raions": [
            "Баштанський район",
            "Вознесенський район",
            "Миколаївський район",
            "Первомайський район",
        ],
    },
    "kherson": {
        "name": "Херсонська область",
        "zone": "zone_south",
        "keys": ["херсонська", "khersonska", "херсон", "берислав", "чорнобаївка"],
        "raions": [
            "Бериславський район",
            "Генічеський район",
            "Каховський район",
            "Скадовський район",
            "Херсонський район",
        ],
    },
    "zaporizhia": {
        "name": "Запорізька область",
        "zone": "zone_south",
        "keys": ["запорізька", "zaporizka", "запоріжжя", "вільнянськ", "оріхів", "бердянськ", "мелітополь"],
        "raions": [
            "Бердянський район",
            "Василівський район",
            "Запорізький район",
            "Мелітопольський район",
            "Пологівський район",
        ],
    },
    "crimea": {
        "name": "АР Крим",
        "zone": "zone_south",
        "keys": ["крим", "krym", "севастополь", "сімферополь", "джанкой", "автономна республіка крим"],
        "raions": [
            "Сімферопольський район",
            "м. Севастополь",
            "Бахчисарайський район",
            "Джанкойський район",
            "Євпаторійський район",
            "Керченський район",
            "Курманський (Красногвардійський) район",
            "Перекопський (Красноперекопський) район",
            "Феодосійський район",
            "Ялтинський район",
            "Білогірський район",
        ],
    },

    # Захід
    "lviv": {
        "name": "Львівська область",
        "zone": "zone_west",
        "keys": ["львівська", "lvivska", "львів", "стрий", "червоноград", "дрогобич"],
        "raions": [
            "Дрогобицький район",
            "Золочівський район",
            "Львівський район",
            "Самбірський район",
            "Стрийський район",
            "Червоноградський (Шептицький) район",
            "Яворівський район",
        ],
    },
    "volyn": {
        "name": "Волинська область",
        "zone": "zone_west",
        "keys": ["волинська", "volynska", "луцьк", "ковель", "нововолинськ"],
        "raions": [
            "Володимирський район",
            "Камінь-Каширський район",
            "Ковельський район",
            "Луцький район",
        ],
    },
    "rivne": {
        "name": "Рівненська область",
        "zone": "zone_west",
        "keys": ["рівненська", "rivnenska", "рівне", "дубно", "вараш", "сарни"],
        "raions": [
            "Вараський район",
            "Дубенський район",
            "Рівненський район",
            "Сарненський район",
        ],
    },
    "ternopil": {
        "name": "Тернопільська область",
        "zone": "zone_west",
        "keys": ["тернопільська", "ternopilska", "тернопіль", "чортків", "кременець"],
        "raions": [
            "Кременецький район",
            "Тернопільський район",
            "Чортківський район",
        ],
    },
    "ivano_frankivsk": {
        "name": "Івано-Франківська область",
        "zone": "zone_west",
        "keys": ["івано-франківська", "ivano-frankivska", "івано-франківськ", "калуш", "коломия"],
        "raions": [
            "Верховинський район",
            "Івано-Франківський район",
            "Калуський район",
            "Коломийський район",
            "Косівський район",
            "Надвірнянський район",
        ],
    },
    "khmelnytskyi": {
        "name": "Хмельницька область",
        "zone": "zone_west",
        "keys": ["хмельницька", "khmelnytska", "хмельницький", "кам'янець-подільський", "старокостянтинів"],
        "raions": [
            "Кам'янець-Подільський район",
            "Хмельницький район",
            "Шепетівський район",
        ],
    },
    "zakarpattia": {
        "name": "Закарпатська область",
        "zone": "zone_west",
        "keys": ["закарпатська", "zakarpatska", "ужгород", "мукачево", "хуст"],
        "raions": [
            "Берегівський район",
            "Мукачівський район",
            "Рахівський район",
            "Тячівський район",
            "Ужгородський район",
            "Хустський район",
        ],
    },
    "chernivtsi": {
        "name": "Чернівецька область",
        "zone": "zone_west",
        "keys": ["чернівецька", "chernivetska", "чернівці", "новоселиця"],
        "raions": [
            "Вижницький район",
            "Дністровський район",
            "Чернівецький район",
        ],
    },
}

AVAILABLE_REGIONS = {code: data["name"] for code, data in ALL_REGIONS.items()}

MACRO_ZONES = {
    "zone_north": {
        "title": "🏙 Столиця та Північ",
        "codes": ["kyiv", "kyiv_obl", "chernihiv", "sumy", "zhytomyr"],
    },
    "zone_east": {
        "title": "🧭 Схід України",
        "codes": ["kharkiv", "donetsk", "luhansk"],
    },
    "zone_center": {
        "title": "🧭 Центр України",
        "codes": ["dnipro", "poltava", "cherkasy", "kirovohrad", "vinnytsia"],
    },
    "zone_south": {
        "title": "🧭 Південь України",
        "codes": ["odesa", "mykolaiv", "kherson", "zaporizhia", "crimea"],
    },
    "zone_west": {
        "title": "🧭 Захід України",
        "codes": ["lviv", "volyn", "rivne", "ternopil", "ivano_frankivsk", "khmelnytskyi", "zakarpattia", "chernivtsi"],
    },
}

AVAILABLE_HORIZONS = {
    "15m": {"label": "⏱ 15 хвилин", "minutes": 15, "factor": 1.0},
    "30m": {"label": "⏱ 30 хвилин", "minutes": 30, "factor": 1.18},
    "1h": {"label": "⏱ 1 година", "minutes": 60, "factor": 1.35},
    "2h": {"label": "⏱ 2 години", "minutes": 120, "factor": 1.55},
}


class ThreatAnalyzer:
    """Evaluates real-time alerts from alerts.in.ua and live OSINT from @kpszsu and @war_monitor."""

    def __init__(self):
        self.live_client = AlertsInUaLiveClient(cache_ttl_seconds=15)

    def analyze_threats_for_region(
        self,
        region_code: str,
        horizon_code: str,
    ) -> Dict[str, Any]:
        reg_meta = ALL_REGIONS.get(region_code, ALL_REGIONS["kyiv"])
        region_name = reg_meta["name"]
        search_keys = reg_meta["keys"]
        raion_names = reg_meta.get("raions", [])
        horizon_info = AVAILABLE_HORIZONS.get(horizon_code, AVAILABLE_HORIZONS["15m"])

        # 1. Fetch live ground-truth status from alerts.in.ua
        live_status = self.live_client.get_region_status(search_keys, region_name, raion_names=raion_names)
        now_kyiv = live_status["timestamp"]
        target_kyiv = now_kyiv + timedelta(minutes=horizon_info["minutes"])

        threat_details = live_status["live_threats"]

        # 2. Probability calculation based on live reality and threat factors
        if live_status["is_alert"]:
            # Region is currently under active sirens/threat
            if live_status["alert_level"] == "NOMINAL":
                base_prob = 0.98
            elif live_status["alert_level"] == "RED":
                base_prob = 0.92
            elif live_status["alert_level"] == "YELLOW":
                base_prob = 0.82
            elif live_status["alert_level"] == "ARTILLERY":
                base_prob = 0.78
            else:
                base_prob = 0.85
            overall_prob = float(np.clip(base_prob * (1.0 - (horizon_info["minutes"] - 15) * 0.001), 0.70, 0.99))
        else:
            # Region currently clear (Відбій) -> probability of NEW alert starting
            has_ballistic_threat = threat_details["ballistics"]["active"]
            has_mig31_threat = threat_details["mig31"]["active"]
            has_shahed_threat = threat_details["shahed"]["active"]

            border_regions = ["kharkiv", "sumy", "zaporizhia", "dnipro", "chernihiv", "donetsk", "kherson", "mykolaiv"]
            is_border = region_code in border_regions

            if has_mig31_threat:
                base_prob = 0.85
            elif has_ballistic_threat and is_border:
                base_prob = 0.70
            elif has_ballistic_threat:
                base_prob = 0.38
            elif has_shahed_threat and is_border:
                base_prob = 0.45
            elif is_border:
                base_prob = 0.22
            else:
                base_prob = 0.08

            overall_prob = float(np.clip(base_prob * horizon_info["factor"], 0.04, 0.94))

        return {
            "region_code": region_code,
            "region_name": region_name,
            "horizon_label": horizon_info["label"],
            "horizon_minutes": horizon_info["minutes"],
            "current_kyiv_time": now_kyiv,
            "target_kyiv_time": target_kyiv,
            "overall_probability": overall_prob,
            "live_status": live_status,
            "threats": threat_details,
        }


def format_interactive_forecast_response(data: Dict[str, Any]) -> str:
    """Builds a rich, customized Telegram message indicating the live alerts status, raions, and threats."""
    reg = data["region_name"]
    horizon = data["horizon_label"]
    prob = data["overall_probability"]
    now_str = data["current_kyiv_time"].strftime("%H:%M:%S")
    target_str = data["target_kyiv_time"].strftime("%H:%M")
    live = data["live_status"]
    threats = data["threats"]

    # Visual risk badge for probability
    if prob < 0.20:
        badge = "🟢 <b>НИЗЬКИЙ РИЗИК</b>"
        progress = "🟩 [■□□□□□□□□□]"
    elif prob < 0.50:
        badge = "🟡 <b>ПІДВИЩЕНИЙ РИЗИК</b>"
        progress = "🟨 [■■■■□□□□□□]"
    elif prob < 0.75:
        badge = "🟠 <b>ВИСОКИЙ РИЗИК</b>"
        progress = "🟧 [■■■■■■■□□□]"
    else:
        badge = "🔴 <b>КРИТИЧНА НЕБЕЗПЕКА</b>"
        progress = "🟥 [■■■■■■■■■■]"

    lines = [
        "🎯 <b>ОПЕРАТИВНИЙ ПРОГНОЗ ЗАГРОЗИ</b>",
        f"📍 <b>Регіон:</b> {reg}",
        f"🕒 <b>Оновлено о:</b> {now_str} (Київський час)",
        f"⏳ <b>Горизонт прогнозу:</b> {horizon} (до {target_str} за Києвом)",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📡 <b>ПОТОЧНИЙ СТАН (alerts.in.ua):</b>",
        f"{live['badge']}",
        f"{live['status_text']}",
    ]

    if live["is_alert"]:
        if live.get("duration_info"):
            lines.append(f"⏱ <b>{live['duration_info']}</b>")
        if live.get("affected_areas"):
            lines.append(f"📍 <b>Охоплені райони:</b> {live['affected_areas']}")
        lines.append("")
        lines.append(f"📊 <b>Ймовірність дії/тривання тривоги:</b> <b>{prob * 100:.1f}%</b>")
    else:
        lines.append(f"📍 <b>Стан:</b> {live['affected_areas']}")
        lines.append("")
        lines.append(f"📊 <b>Ймовірність виникнення НОВОЇ тривоги:</b> <b>{prob * 100:.1f}%</b>")

    lines.extend([
        f"Статус оцінки: {badge} {progress}",
    ])

    # Per-raion status breakdown
    raions = live.get("raions", [])
    if raions:
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "🏘 <b>СТАН ПО ВСІХ РАЙОНАХ:</b>",
        ])
        for r in raions:
            lines.append(f"• {r['badge']} <b>{r['name']}</b> — {r['status']}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🚨 <b>ЯКА САМЕ ЗАГРОЗА ФІКСУЄТЬСЯ:</b>",
        "",
        f"🚀 <b>Балістичні ракети:</b>\n   └ {threats['ballistics']['desc']}",
        "",
        f"🛸 <b>Ударні дрони (Shahed):</b>\n   └ {threats['shahed']['desc']}",
        "",
        f"💣 <b>Тактична авіація (КАБ):</b>\n   └ {threats['aviation']['desc']}",
        "",
        f"✈️ <b>Швидкісні цілі (МіГ-31К / Кинджал):</b>\n   └ {threats['mig31']['desc']}",
        "",
        f"🛑 <b>Крилаті ракети (Калібр / Х-101):</b>\n   └ {threats['missile']['desc']}",
    ])

    raw_msgs = threats.get("raw_messages", [])
    if raw_msgs:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📢 <b>ОПЕРАТИВНІ ЗВЕДЕННЯ РАДАРІВ:</b>")
        for m in raw_msgs[:2]:
            lines.append(f"• <i>{m}</i>")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📡 <i>Дані надходять наживо з alerts.in.ua, @kpszsu та @war_monitor.</i>",
        "🔔 <i>Під час повітряної тривоги негайно перебувайте в укриттях!</i>",
    ])

    return "\n".join(lines)


def format_region_selection_overview(region_code: str) -> str:
    """Builds the comprehensive region status message showing all raions upon region selection."""
    analyzer = ThreatAnalyzer()
    reg_meta = ALL_REGIONS.get(region_code, ALL_REGIONS["kyiv"])
    region_name = reg_meta["name"]
    search_keys = reg_meta["keys"]
    raion_names = reg_meta.get("raions", [])

    live = analyzer.live_client.get_region_status(search_keys, region_name, raion_names=raion_names)
    now_str = live["timestamp"].strftime("%H:%M:%S")

    lines = [
        f"📍 <b>{region_name.upper()} — ОПЕРАТИВНИЙ СТАН</b>",
        f"🕒 <b>Оновлено о:</b> {now_str} (Київський час)",
        f"📡 <b>Загальний статус (alerts.in.ua):</b> {live['badge']}",
        f"{live['status_text']}",
    ]
    if live.get("duration_info"):
        lines.append(f"⏱ <b>{live['duration_info']}</b>")
    if live.get("affected_areas"):
        lines.append(f"📍 <b>Охоплено:</b> {live['affected_areas']}")

    raions = live.get("raions", [])
    if raions:
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "🏘 <b>СТАН ПО КОЖНОМУ РАЙОНУ:</b>",
        ])
        for r in raions:
            lines.append(f"• {r['badge']} <b>{r['name']}</b> — {r['status']}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "⏱ <b>Оберіть часовий горизонт прогнозу загрози:</b>",
    ])
    return "\n".join(lines)


def get_macro_zones_keyboard() -> dict:
    """Builds Telegram Inline Keyboard for Macro-Zones selection."""
    keyboard = [
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
    ]
    return {"inline_keyboard": keyboard}


def get_zone_regions_keyboard(zone_key: str) -> dict:
    """Builds Telegram Inline Keyboard for regions within a macro-zone."""
    zone_data = MACRO_ZONES.get(zone_key)
    keyboard = []
    if zone_data:
        codes = zone_data["codes"]
        for i in range(0, len(codes), 2):
            row = []
            for c in codes[i : i + 2]:
                row.append({"text": f"📍 {ALL_REGIONS[c]['name']}", "callback_data": f"reg_{c}"})
            keyboard.append(row)
    keyboard.append([{"text": "⬅️ Назад до макрорегіонів", "callback_data": "menu_zones"}])
    return {"inline_keyboard": keyboard}


def get_all_regions_keyboard() -> dict:
    """Builds Telegram Inline Keyboard listing all 26 regions alphabetically."""
    keyboard = []
    codes = list(ALL_REGIONS.keys())
    codes.sort(key=lambda c: ALL_REGIONS[c]["name"])
    for i in range(0, len(codes), 2):
        row = []
        for c in codes[i : i + 2]:
            row.append({"text": f"📍 {ALL_REGIONS[c]['name']}", "callback_data": f"reg_{c}"})
        keyboard.append(row)
    keyboard.append([{"text": "⬅️ Назад до макрорегіонів", "callback_data": "menu_zones"}])
    return {"inline_keyboard": keyboard}


def get_region_keyboard() -> dict:
    """Primary entry point returning macro-zones keyboard."""
    return get_macro_zones_keyboard()


def get_horizon_keyboard(region_code: str) -> dict:
    """Builds Telegram Inline Keyboard for horizon selection."""
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
            {"text": "⬅️ Назад до вибору області", "callback_data": zone_code},
            {"text": "📍 Усі регіони", "callback_data": "menu_zones"},
        ],
    ]
    return {"inline_keyboard": keyboard}


def simulate_user_flow(region_code: str = "sumy", horizon_code: str = "1h"):
    """Simulates the interactive flow in terminal without needing live bot tokens."""
    analyzer = ThreatAnalyzer()
    print("\n" + "=" * 70)
    print("СИМУЛЯЦІЯ ДІАЛОГУ З ТЕЛЕГРАМ-БОТОМ (НАЖИВО З alerts.in.ua):")
    print("=" * 70)

    reg_name = ALL_REGIONS.get(region_code, {}).get("name", region_code)
    print("\n[Користувач]: /forecast")
    print("[Бот надсилає меню макрорегіонів]")
    print(f"\n[Користувач обирає область]: '📍 {reg_name}'")

    overview = format_region_selection_overview(region_code)
    print("\n[Бот надає оперативний стан та стан по кожному району області]:")
    print("-" * 50)
    print(overview)
    print("-" * 50)

    print(f"\n[Користувач обирає горизонт]: '{AVAILABLE_HORIZONS[horizon_code]['label']}'")
    print("\n[Бот отримує живий статус з alerts.in.ua та формує детальний прогноз з аналізом загроз...]")

    result = analyzer.analyze_threats_for_region(region_code, horizon_code)
    formatted_msg = format_interactive_forecast_response(result)

    print("\n" + "=" * 70)
    print(formatted_msg)
    print("=" * 70 + "\n")


def telegram_api_call(token: str, method: str, payload: dict) -> dict:
    """Invokes the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[-] Telegram API Error ({method}): {exc}", flush=True)
        return {"ok": False, "description": str(exc)}


def run_live_polling(token: str):
    """Runs long polling loop to serve user queries interactively in Telegram."""
    print("=" * 70, flush=True)
    print("ЗАПУСК ІНТЕРАКТИВНОГО ТЕЛЕГРАМ-БОТА (LONG POLLING)", flush=True)
    print("Підключення до alerts.in.ua, @kpszsu та @war_monitor наживо...", flush=True)
    print("=" * 70, flush=True)
    analyzer = ThreatAnalyzer()
    offset = 0

    # Test token
    me = telegram_api_call(token, "getMe", {})
    if not me.get("ok"):
        print(f"[!] Не вдалося підключитися до Telegram Bot API: {me.get('description')}", flush=True)
        return
    bot_user = me["result"]["username"]
    print(f"[+] Бот @{bot_user} успішно підключено та очікує повідомлень користувачів...\n", flush=True)

    while True:
        try:
            updates = telegram_api_call(token, "getUpdates", {"offset": offset, "timeout": 25})
            if not updates.get("ok"):
                time.sleep(2)
                continue

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                # 1. Direct message command (/start, /forecast, or region names)
                if "message" in u and "text" in u["message"]:
                    chat_id = u["message"]["chat"]["id"]
                    text = u["message"]["text"].strip()
                    user_name = u["message"].get("from", {}).get("first_name", "Користувач")
                    print(f"[>] Повідомлення від {user_name} (chat_id={chat_id}): '{text}'", flush=True)

                    # Check if text directly asks for a known region
                    matched_code = None
                    clean_text = text.lower().lstrip("/")
                    for r_code, r_meta in ALL_REGIONS.items():
                        if clean_text in [r_code, r_meta["name"].lower()]:
                            matched_code = r_code
                            break
                        if any(k in clean_text for k in r_meta["keys"] if len(k) >= 4):
                            matched_code = r_code
                            break

                    if matched_code:
                        overview = format_region_selection_overview(matched_code)
                        telegram_api_call(token, "sendMessage", {
                            "chat_id": chat_id,
                            "text": overview,
                            "parse_mode": "HTML",
                            "reply_markup": get_horizon_keyboard(matched_code),
                        })
                    else:
                        welcome_text = (
                            f"👋 <b>Вітаю, {user_name}!</b>\n\n"
                            "Я — оперативний аналітичний бот моніторингу повітряних загроз в Україні.\n\n"
                            "📡 <b>Дані надходять у реальному часі з alerts.in.ua, @kpszsu та @war_monitor.</b>\n\n"
                            "Ви можете переглянути:\n"
                            "• 🔴/🟡 <b>Рівень тривоги</b> (Червоний, Жовтий, Артобстріл, Номінальна, Відбій)\n"
                            "• 🏘 <b>Детальну інформацію по кожному району області</b>\n"
                            "• ⏱ <b>Точний час тривання та охоплені громади</b>\n"
                            "• 📊 <b>Ймовірнісний прогноз на вибраний горизонт</b>\n"
                            "• 🚨 <b>Яка саме загроза фіксується</b> (дрон Shahed, балістика, КАБ, МіГ-31К, ракети)\n\n"
                            "📍 <b>Оберіть макрорегіон або перегляньте всі області:</b>"
                        )
                        telegram_api_call(token, "sendMessage", {
                            "chat_id": chat_id,
                            "text": welcome_text,
                            "parse_mode": "HTML",
                            "reply_markup": get_macro_zones_keyboard(),
                        })

                # 2. Inline button clicks (Callback queries)
                elif "callback_query" in u:
                    cq = u["callback_query"]
                    cq_id = cq["id"]
                    data = cq.get("data", "")
                    chat_id = cq["message"]["chat"]["id"]
                    message_id = cq["message"]["message_id"]
                    cb_user = cq.get("from", {}).get("first_name", "Користувач")

                    # Answer callback query to stop loading spinner
                    telegram_api_call(token, "answerCallbackQuery", {"callback_query_id": cq_id})
                    print(f"[>] Клік від {cb_user}: '{data}'", flush=True)

                    if data in ["menu_zones", "menu_regions"]:
                        telegram_api_call(token, "editMessageText", {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": "📍 <b>Оберіть макрорегіон або перегляньте всі області:</b>",
                            "parse_mode": "HTML",
                            "reply_markup": get_macro_zones_keyboard(),
                        })

                    elif data == "zone_all":
                        telegram_api_call(token, "editMessageText", {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": "📍 <b>Усі 26 областей України (за алфавітом):</b>",
                            "parse_mode": "HTML",
                            "reply_markup": get_all_regions_keyboard(),
                        })

                    elif data in MACRO_ZONES:
                        zone_title = MACRO_ZONES[data]["title"]
                        telegram_api_call(token, "editMessageText", {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": f"📍 <b>{zone_title} — Оберіть вашу область:</b>",
                            "parse_mode": "HTML",
                            "reply_markup": get_zone_regions_keyboard(data),
                        })

                    elif data.startswith("reg_"):
                        region_code = data.replace("reg_", "")
                        region_overview = format_region_selection_overview(region_code)
                        telegram_api_call(token, "editMessageText", {
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": region_overview,
                            "parse_mode": "HTML",
                            "reply_markup": get_horizon_keyboard(region_code),
                        })

                    elif data.startswith("hor_"):
                        parts = data.split("_")
                        if len(parts) >= 3:
                            region_code = parts[1]
                            horizon_code = parts[2]

                            # Calculate live status and personal threat prediction
                            res = analyzer.analyze_threats_for_region(region_code, horizon_code)
                            reply_text = format_interactive_forecast_response(res)

                            action_keyboard = {
                                "inline_keyboard": [
                                    [
                                        {"text": "🔄 Оновити прогноз", "callback_data": f"hor_{region_code}_{horizon_code}"},
                                        {"text": "⏱ Інший час", "callback_data": f"reg_{region_code}"},
                                    ],
                                    [{"text": "📍 Змінити область", "callback_data": "menu_zones"}],
                                ]
                            }

                            telegram_api_call(token, "editMessageText", {
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "text": reply_text,
                                "parse_mode": "HTML",
                                "reply_markup": action_keyboard,
                            })

            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[+] Зупинка бота за запитом користувача.", flush=True)
            break
        except Exception as exc:
            print(f"[!] Непередбачена помилка: {exc}", flush=True)
            time.sleep(3)


def load_env_file(env_path: str = ".env") -> None:
    """Loads environment variables from .env file if it exists."""
    p = Path(env_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and (k not in os.environ or not os.environ[k]):
                            os.environ[k] = v
        except Exception:
            pass


def is_valid_token(t: Optional[str]) -> bool:
    """Checks if token has proper telegram bot format."""
    if not t or not isinstance(t, str):
        return False
    t_clean = t.strip()
    try:
        t_clean.encode("ascii")
    except UnicodeEncodeError:
        return False
    return bool(re.match(r"^\d+:[A-Za-z0-9_-]+$", t_clean))


if __name__ == "__main__":
    load_env_file()

    token = None
    # 1. Check CLI args for --token
    for idx, arg in enumerate(sys.argv):
        if arg == "--token" and idx + 1 < len(sys.argv):
            token = sys.argv[idx + 1].strip()
            break
        elif arg.startswith("--token="):
            token = arg.split("=", 1)[1].strip()
            break

    # 2. Check environment variable
    if not token:
        for k in ["TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN", "TOKEN"]:
            val = os.environ.get(k)
            if val:
                token = val.strip().strip('"').strip("'").strip()
                if is_valid_token(token):
                    break

    is_live = "--live" in sys.argv or (bool(token) and "--simulate" not in sys.argv and len(sys.argv) == 1)

    if is_live:
        if not is_valid_token(token):
            print("[!] Помилка: Некоректний Telegram Bot Token.", flush=True)
            print("    Будь ласка, вкажіть дійсний токен у лапках у PowerShell:", flush=True)
            print('    $env:TELEGRAM_BOT_TOKEN="123456789:ABCdefGhI..."', flush=True)
            print("    або передайте прапорцем:", flush=True)
            print('    .\\.venv\\Scripts\\python.exe -m src.bot.interactive_bot --token "123456789:ABCdefGhI..."', flush=True)
            sys.exit(1)
        run_live_polling(token)
    else:
        reg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "sumy"
        hor = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "1h"
        simulate_user_flow(region_code=reg, horizon_code=hor)
