"""Telegram Message Formatter for 15-Minute Air Raid Forecasts.

Formats probability outputs and multi-channel OSINT intelligence
into clean, actionable Telegram posts.
"""

from datetime import datetime
from typing import Optional, Dict, Any


def render_risk_bar(prob: float, length: int = 10) -> str:
    """Renders a visual ASCII progress bar for probability."""
    filled = int(round(prob * length))
    filled = max(0, min(length, filled))
    empty = length - filled
    if prob < 0.15:
        emoji = "🟩"
    elif prob < 0.40:
        emoji = "🟨"
    else:
        emoji = "🟥"
    return f"{emoji} [{'■' * filled}{'□' * empty}]"


def get_risk_badge(prob: float) -> str:
    """Determines textual and color badge of threat."""
    if prob < 0.15:
        return "🟢 <b>НИЗЬКИЙ РИЗИК</b>"
    elif prob < 0.40:
        return "🟡 <b>ПІДВИЩЕНИЙ РИЗИК</b>"
    else:
        return "🔴 <b>ВИСОКИЙ РИЗИК (ЗАГРОЗА)</b>"


def format_forecast_post(
    region_name: str,
    timestamp: datetime,
    is_active: bool,
    current_duration_min: float,
    prob_15m: float,
    prob_30m: float,
    prob_60m: float,
    osint_signals: Dict[str, Any],
) -> str:
    """Generates an HTML-formatted Telegram post for the 15-minute interval."""
    # Convert timestamp to Kyiv local time representation (UTC+2 or UTC+3)
    time_str = timestamp.strftime("%H:%M")
    date_str = timestamp.strftime("%d.%m.%Y")

    status_icon = "🔴" if is_active else "🟢"
    status_text = (
        f"<b>ТРИВАЄ ТРИВОГА</b> (триває {int(current_duration_min)} хв)"
        if is_active
        else "<b>СПОКІЙНО</b> (сирени відключені)"
    )

    lines = [
        f"🛡 <b>ПРОГНОЗ ПОВІТРЯНИХ ЗАГРОЗ | {region_name.upper()}</b>",
        f"⏱ <i>Зріз: {time_str} ({date_str})</i>",
        "",
        f"📍 <b>Поточний стан:</b> {status_icon} {status_text}",
        "",
    ]

    if not is_active:
        lines.extend([
            "📊 <b>Ймовірність виникнення нової тривоги:</b>",
            f"• <b>+15 хв:</b> {prob_15m * 100:.1f}% {render_risk_bar(prob_15m)}",
            f"• <b>+30 хв:</b> {prob_30m * 100:.1f}% {render_risk_bar(prob_30m)}",
            f"• <b>+60 хв:</b> {prob_60m * 100:.1f}% {render_risk_bar(prob_60m)}",
            "",
            f"🎯 <b>Рівень небезпеки:</b> {get_risk_badge(prob_15m)}",
        ])
    else:
        prob_clear_15m = max(0.01, 1.0 - prob_15m)
        lines.extend([
            "📊 <b>Оцінка продовження / відбою:</b>",
            f"• Ймовірність відбою в найближчі 15 хв: <b>{prob_clear_15m * 100:.1f}%</b>",
            f"• Тривога триватиме ще щонайменше 15 хв: <b>{prob_15m * 100:.1f}%</b>",
            "",
            "⚠️ <i>Перебувайте в безпечних місцях або правилі двох стін до сигналу відбою.</i>",
        ])

    lines.append("")
    lines.append("📡 <b>Оперативні OSINT-сигнали (@kpszsu, @war_monitor, @raketa_trevoga):</b>")

    shahed_active = osint_signals.get("tg_shahed", 0) > 0
    ballistics_active = osint_signals.get("tg_ballistics", 0) > 0
    aviation_active = osint_signals.get("tg_aviation", 0) > 0
    mig31_active = osint_signals.get("tg_mig31", 0) > 0
    missile_active = osint_signals.get("tg_missile", 0) > 0
    targeted = osint_signals.get("tg_kyiv_targeted", 0) > 0

    if ballistics_active:
        lines.append("• 🔴 <b>Балістична загроза:</b> зафіксовано маркери пусків/швидкісних цілей!")
    if shahed_active:
        vector_text = " (вектор на регіон!)" if targeted else ""
        lines.append(f"• 🟠 <b>Ударні БпЛА (Shahed):</b> активність у повітряному просторі{vector_text}")
    if mig31_active:
        lines.append("• 🔴 <b>Зліт МіГ-31К:</b> потенційна масштабна загроза 'Кинджал'")
    if aviation_active:
        lines.append("• 🟡 <b>Тактична авіація:</b> пуски КАБ / активність вздовж кордону")
    if missile_active:
        lines.append("• 🔴 <b>Крилаті ракети / Стратегічна авіація:</b> підвищена готовність")

    if not any([shahed_active, ballistics_active, aviation_active, mig31_active, missile_active]):
        lines.append("• 🟢 <i>Прямих сигналів загроз на радарах та моніторингових каналах не виявлено.</i>")

    lines.append("")
    lines.append("🔔 <i>Оновлення кожні 15 хвилин. Слідкуйте за офіційними повідомленнями влади.</i>")

    return "\n".join(lines)
