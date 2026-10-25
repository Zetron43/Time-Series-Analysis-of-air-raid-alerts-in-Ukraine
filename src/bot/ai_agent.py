"""AI Agent Module for Air Raid Monitoring Telegram Bot.

Powered by Google Gemini with Automatic Function Calling / Tool Use.
Enables natural language reasoning, tactical analysis, and tool execution.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")

AGENT_SYSTEM_INSTRUCTION = """Ти — спеціалізований оперативний ШІ-агент "Вартовий Неба", військово-аналітичний асистент моніторингу повітряних загроз в Україні.

Твоє завдання:
1. Аналізувати ситуацію з повітряними тривогами, ракетними загрозами та ворожими БпЛА (Shahed, балістика, крилаті ракети, тактична/стратегічна авіація).
2. Надавати швидкі, точні, спокійні та лаконічні відповіді українською мовою.
3. Використовувати підключені інструменти (Tools) для отримання актуальних даних у реальному часі:
   - `get_live_alerts_overview` — для загальної картини по Україні чи конкретній області.
   - `analyze_threat_forecast` — для ймовірнісного прогнозу збереження або початку тривоги в конкретній області чи районі на обраний горизонт (15хв, 30хв, 1год, 2год).
   - `get_radar_drones_status` — для отримання даних радарів Neptun та Dimap про координати, кількість цілей та курс БпЛА.
   - `manage_user_tracking` — для перегляду або додавання районів слідкування для користувача.

Правила взаємодії:
- Відповідай оперативно, лаконічно та структуровано (3–4 коротких пункти з емодзі 🚨, 🛸, 📍, ⏱, 🛡). Без довгих вступів та зайвої води.
- Якщо користувач запитує про безпеку, тривогу чи загрозу в певному місті/районі/області — виклич відповідний інструмент, щоб мати свіжі дані.
- КРИТИЧНО ВАЖЛИВО розрізняти:
  1) Офіційна тривога: сирени увімкнено безпосередньо в районі / місті.
  2) Раннє попередження: сирени у районі ще НЕ лунають, але радари фіксують загрозу (БпЛА на підльоті або тривога в сусідньому районі). Завжди прямо повідомляй користувачеві, коли це раннє попередження, щоб уникати паніки!
- Якщо є пряма загроза чи офіційна тривога — нагадуй про безпеку та укриття.
"""


def format_ai_markdown_to_html(text: str) -> str:
    """Converts AI markdown formatting to Telegram-compatible HTML tags."""
    if not text:
        return ""
    # Convert **bold** to <b>bold</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Convert single *italic* to <i>italic</i> when not inside an HTML tag
    text = re.sub(r"(?<![<a-zA-Z0-9])\*([^\*\n]+?)\*(?![>a-zA-Z0-9])", r"<i>\1</i>", text)
    return text



class AirRaidAIAgent:
    """Intelligent conversational AI agent with Gemini Tool Calling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.5-flash-lite",
    ):
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.api_key = api_key
        # Default to stable, high-speed lightweight Gemini Flash Lite model
        self.model_name = model_name
        self._client = None
        self._init_client()

    def _init_client(self):
        """Initializes the google-genai Client if package and API key are available."""
        if not self.api_key:
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except Exception as e:
            print(f"[-] AI Agent: Error initializing google-genai client: {e}", flush=True)
            self._client = None

    def is_configured(self) -> bool:
        """Returns True if the agent is ready with a valid API key and SDK."""
        return self._client is not None and bool(self.api_key)

    # -------------------------------------------------------------------------
    # Tool Declarations (Functions with docstrings used by Gemini)
    # -------------------------------------------------------------------------

    @staticmethod
    def get_live_alerts_overview(region_filter: str = "") -> str:
        """Отримує поточну оперативну інформацію про активні повітряні тривоги по всій Україні або конкретній області/району.

        Args:
            region_filter: Назва області або конкретного району (наприклад: 'київська', 'дністровський', 'харків', 'львів'). Якщо порожньо — повертає зведення по всіх тривогах в Україні.
        """
        try:
            from src.ingestion.alerts_live_client import AlertsInUaLiveClient
            from src.bot.interactive_bot import ALL_REGIONS

            client = AlertsInUaLiveClient()
            now_str = datetime.now(KYIV_TZ).strftime("%H:%M:%S")

            if region_filter:
                rf = region_filter.lower().strip()
                # 1. First check if it matches a specific raion directly
                all_raions_status = client.get_all_raions_live_status()
                for r_name, r_info in all_raions_status.items():
                    r_clean = r_name.lower().replace(" район", "").strip()
                    if rf == r_clean or rf in r_name.lower():
                        lvl = r_info.get("level", "CLEAR")
                        badge = r_info.get("badge", "🟢")
                        status_str = r_info.get("status", "Спокійно")
                        obl = r_info.get("region_name", "")
                        if r_info.get("active"):
                            return f"Станом на {now_str} у районі {r_name} ({obl}) ОГОЛОШЕНО ТРИВОГУ! Рівень: {lvl} {badge}. Стан: {status_str}."
                        else:
                            return f"Станом на {now_str} у районі {r_name} ({obl}) тривоги НЕМАЄ (спокійно, сирени не лунають). Стан: {status_str}."

                # 2. Check if it matches an oblast
                for r_code, r_meta in ALL_REGIONS.items():
                    r_name = r_meta.get("name", "")
                    if rf in r_name.lower() or rf in r_code.lower() or any(k in rf for k in r_meta.get("keys", [])):
                        reg_status = client.get_region_status(
                            r_meta.get("keys", [r_code]),
                            r_name,
                            raion_names=r_meta.get("raions", []),
                        )
                        raions = reg_status.get("raions", [])
                        active_raions = [r for r in raions if r.get("active")]
                        clear_raions = [r for r in raions if not r.get("active")]

                        if active_raions:
                            active_desc = ", ".join([f"{r['name']} ({r['badge']} {r['status']})" for r in active_raions])
                            clear_desc = f"{len(clear_raions)} районів спокійні" if clear_raions else "усі райони під тривогою"
                            return (
                                f"Станом на {now_str} в області {r_name} тривога діє лише в окремих районах: {active_desc}.\n"
                                f"В іншій частині області: {clear_desc} (сирени не лунають)."
                            )
                        else:
                            return f"Станом на {now_str} в області {r_name} повітряної тривоги немає в жодному з районів (чисто, сирени не лунають)."

            # Countrywide overview
            active_regions = []
            for r_code, r_meta in ALL_REGIONS.items():
                status = client.get_region_status(
                    region_search_keys=r_meta.get("keys", [r_code]),
                    region_name=r_meta.get("name", r_code),
                    raion_names=r_meta.get("raions", []),
                )
                if status.get("is_alert"):
                    active_r = [r["name"] for r in status.get("raions", []) if r.get("active")]
                    r_summary = f"{len(active_r)}/{len(status.get('raions', []))} районів" if active_r else "вся область"
                    active_regions.append({
                        "name": r_meta["name"],
                        "threat": status.get("badge", "Повітряна тривога"),
                        "raions_str": r_summary,
                    })

            if not active_regions:
                return f"Станом на {now_str} в Україні активних тривог немає (чисте небо по всіх районах)."

            reg_names = [f"• {r['name']} ({r['threat']}, охоплено: {r['raions_str']})" for r in active_regions]
            return f"Станом на {now_str} повітряна тривога активна у {len(active_regions)} областях (по окремих або всіх районах):\n" + "\n".join(reg_names)
        except Exception as e:
            return f"Помилка отримання даних alerts.in.ua: {e}"

    @staticmethod
    def analyze_threat_forecast(
        region: str,
        horizon: str = "1h",
        raion_name: str = "",
    ) -> str:
        """Розраховує математичну ймовірність загрози та тривалості тривоги на основі моделі аналізу часових рядів, радарів та моніторингових джерел.

        Args:
            region: Область України (наприклад: 'київська', 'сумська', 'дніпропетровська', 'львівська').
            horizon: Горизонт прогнозу: '15m' (15 хв), '30m' (30 хв), '1h' (1 година), '2h' (2 години).
            raion_name: Назва конкретного району (наприклад: 'Шосткинський район', 'Бучанський район').
        """
        try:
            from src.bot.interactive_bot import ALL_REGIONS, ThreatAnalyzer

            # Match region code
            matched_code = "kyiv"
            r_lower = region.lower().strip()
            for code, meta in ALL_REGIONS.items():
                if r_lower in code.lower() or r_lower in meta["name"].lower() or any(k in r_lower for k in meta["keys"]):
                    matched_code = code
                    break

            analyzer = ThreatAnalyzer()
            res = analyzer.analyze_threats_for_region(
                region_code=matched_code,
                horizon_code=horizon if horizon in ["15m", "30m", "1h", "2h"] else "1h",
                raion_name=raion_name or None,
            )

            live = res.get("live_status", {})
            is_official = res.get("is_official_alarm", False)
            is_warning = res.get("has_radar_warning", False)
            if is_official:
                status_str = f"🚨 ОФІЦІЙНА ТРИВОГА (сирени активні)"
            elif is_warning:
                status_str = f"⚠️ РАННЄ ПОПЕРЕДЖЕННЯ: загроза БпЛА / радари (сирени в районі ще НЕ лунають)"
            elif res.get("neighbors_alarms"):
                status_str = f"⚠️ РАННЄ ПОПЕРЕДЖЕННЯ: тривога у {len(res['neighbors_alarms'])} сусідніх районах (у цьому районі чисто)"
            else:
                status_str = "🟢 ВІДБІЙ (спокійно, сирени не лунають)"

            active_threats = []
            for t_k, t_info in res.get("threats", {}).items():
                if isinstance(t_info, dict) and t_info.get("active"):
                    active_threats.append(t_info.get("scale_title") or t_k)

            # Local drone certainty
            drone_report = ""
            conf_cnt = res.get("local_confirmed_count", 0)
            prob_cnt = res.get("local_probable_count", 0)
            if conf_cnt > 0 or prob_cnt > 0:
                drone_report = f"- БпЛА в зоні району: 🔴 {conf_cnt} підтверджено радарами, 🟡 {prob_cnt} ймовірних / дорозвідка\n"

            return (
                f"Аналітичний прогноз для {res['region_name']} (Район: {res.get('raion_name', 'вся область')}):\n"
                f"- Поточний стан: {status_str}\n"
                f"{drone_report}"
                f"- Зафіксовані загрози: {', '.join(active_threats) if active_threats else 'не зафіксовано'}\n"
                f"- Ймовірність небезпеки на горизонті {horizon}: {res['overall_probability']*100:.1f}%\n"
                f"- Пояснення: {res['prob_explanation']}"
            )
        except Exception as e:
            return f"Помилка розрахунку прогнозу: {e}"

    @staticmethod
    def get_radar_drones_status() -> str:
        """Опитує радіолокаційні системи Neptun та Dimap про місцезнаходження, кількість та класифікацію ворожих БпЛА (підтверджені радарами vs ймовірні / дорозвідка)."""
        try:
            from src.ingestion.neptun_client import NeptunClient

            nep = NeptunClient()
            threats = nep.get_threats()
            classified = nep.classify_drones(threats)

            total = classified["total_count"]
            conf_cnt = classified["confirmed_count"]
            prob_cnt = classified["probable_count"]
            confirmed_list = classified["confirmed_threats"]
            probable_list = classified["probable_threats"]

            if total == 0 and not threats:
                return "Радари Neptun у даний момент не фіксують активних БпЛА у повітряному просторі України."

            report = [
                f"Радари Neptun фіксують у повітряному просторі України {total} БпЛА:",
                f"• 🔴 Підтверджені радарами: {conf_cnt} од.",
                f"• 🟡 Ймовірні / розрахункові (дорозвідка/акустично): {prob_cnt} од.",
                "",
                "Деталі по підтверджених цілях:",
            ]

            if confirmed_list:
                for idx, t in enumerate(confirmed_list[:5], 1):
                    heading = t.get("heading")
                    h_str = f", курс {int(heading)}°" if heading is not None else ""
                    loc = t.get("region") or t.get("district") or t.get("locality") or "повітряний простір України"
                    cnt = t.get("count", 1) or 1
                    report.append(f"{idx}. 🔴 {t.get('title', 'БпЛА')} (x{cnt}) — {loc}{h_str} (джерел: {t.get('sourceCount', 1)})")
            else:
                report.append("  (немає цілей з високим підтвердженням)")

            if probable_list:
                report.append("")
                report.append("Ймовірні цілі (дорозвідка / акустичні звіти):")
                for idx, t in enumerate(probable_list[:5], 1):
                    heading = t.get("heading")
                    h_str = f", курс {int(heading)}°" if heading is not None else ""
                    loc = t.get("region") or t.get("district") or t.get("locality") or "повітряний простір України"
                    report.append(f"{idx}. 🟡 {t.get('title', 'БпЛА')} — {loc}{h_str} (статус: {t.get('positionQuality', 'ймовірна')})")

            return "\n".join(report)
        except Exception as e:
            return f"Помилка опитування радарів Neptun: {e}"

    @staticmethod
    def manage_user_tracking(chat_id: int, action: str = "list", raion_name: str = "") -> str:
        """Керує списком районів користувача для отримання ранніх автоматичних сповіщень.

        Args:
            chat_id: Telegram ID чату користувача.
            action: 'list' (показати підписки), 'add' (додати район), 'remove' (видалити район).
            raion_name: Назва району (потрібна для add або remove, наприклад: 'Шосткинський район').
        """
        try:
            from src.bot.subscription_manager import UserSubscriptionManager
            mgr = UserSubscriptionManager()
            if action == "add" and raion_name:
                added = mgr.add_subscription(chat_id, raion_name)
                return f"Район '{raion_name}' успішно додано до відстеження." if added else f"Район '{raion_name}' вже був у списку слідкування."
            elif action == "remove" and raion_name:
                removed = mgr.remove_subscription(chat_id, raion_name)
                return f"Район '{raion_name}' успішно видалено зі списку слідкування." if removed else f"Район '{raion_name}' не знайдено серед підписок."
            else:
                subs = mgr.get_user_subscriptions(chat_id)
                if not subs:
                    return "У вас наразі немає налаштованих районів для автоматичного слідкування."
                return "Ваші активні райони слідкування:\n" + "\n".join([f"• {r}" for r in subs])
        except Exception as e:
            return f"Помилка керування підписками: {e}"

    # -------------------------------------------------------------------------
    # Main Agent Entry Point
    # -------------------------------------------------------------------------

    def answer_query(self, user_query: str, chat_id: int = 0) -> str:
        """Processes user's natural language question using Gemini with Tools."""
        if not self.is_configured():
            return (
                "🤖 <b>ШІ-Агент 'Вартовий Неба' готовий до підключення!</b>\n\n"
                "Щоб активувати природний діалог з інтелектуальним агентом, будь ласка, додайте свій <code>GEMINI_API_KEY</code>.\n\n"
                "🔑 <b>Як отримати ключ безкоштовно:</b>\n"
                "1. Перейдіть на <a href='https://aistudio.google.com/apikey'>Google AI Studio</a>.\n"
                "2. Натисніть <i>'Create API key'</i>.\n"
                "3. Встановіть змінну середовища у Railway (Variables) або в <code>.env</code>:\n"
                "   <code>GEMINI_API_KEY=\"ваш_ключ\"</code>\n\n"
                "💡 <i>Після цього бот зможе відповідати на будь-які ваші запитання людською мовою, використовуючи математичні прогнози та радари!</i>"
            )

        try:
            from google.genai import types

            # Create tools list binding static methods
            tools = [
                AirRaidAIAgent.get_live_alerts_overview,
                AirRaidAIAgent.analyze_threat_forecast,
                AirRaidAIAgent.get_radar_drones_status,
                AirRaidAIAgent.manage_user_tracking,
            ]

            # Context enricher with user chat_id
            augmented_query = f"[User chat_id: {chat_id}]\nЗапит користувача: {user_query}"

            # Invoke Gemini with Automatic Function Calling via Chat session
            # using thinking_level="low" for fastest, lowest-latency response times
            chat = self._client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    system_instruction=AGENT_SYSTEM_INSTRUCTION,
                    tools=tools,
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(thinking_level="low"),
                ),
            )
            response = chat.send_message(augmented_query)

            if response and response.text:
                raw_text = response.text.strip()
                return format_ai_markdown_to_html(raw_text)
            return "Не вдалося сформувати відповідь. Спробуйте уточнити запит."
        except Exception as e:
            err_msg = str(e)
            print(f"[-] AI Agent Error during execution: {err_msg}", flush=True)
            if "API_KEY_INVALID" in err_msg or "API key not valid" in err_msg or ("INVALID_ARGUMENT" in err_msg and "key" in err_msg.lower()):
                return (
                    "⚠️ <b>Помилка ключа Gemini API (Недійсний API-ключ):</b>\n\n"
                    "Google відхилив вказаний ключ API (<code>API_KEY_INVALID</code>).\n\n"
                    "📌 <b>Зверніть увагу:</b> Ключ Google Gemini API <b>завжди починається на <code>AIzaSy...</code></b> (39 символів).\n"
                    "Значення, що починаються на <code>AQ...</code> або <code>4/0...</code>, є тимчасовими кодами авторизації, а не ключами API.\n\n"
                    "🔑 <b>Як отримати правильний ключ безкоштовно:</b>\n"
                    "1. Відкрийте <a href='https://aistudio.google.com/apikey'>Google AI Studio (API Keys)</a>.\n"
                    "2. Натисніть кнопку <b>'Create API key'</b>.\n"
                    "3. Скопіюйте ключ, що починається на <code>AIzaSy...</code>.\n"
                    "4. Оновіть змінну <code>GEMINI_API_KEY</code> на <b>Railway</b> (Variables) або в файлі <code>.env</code>."
                )
            return (
                f"⚠️ <b>Помилка ШІ-агента:</b> {e}\n\n"
                "Спробуйте скористатися стандартними кнопками меню або уточніть запитання."
            )
