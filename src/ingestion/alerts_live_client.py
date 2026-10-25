"""Live Alerts Client connecting directly to alerts.in.ua live situation report.

Provides real-time:
1. Current alert state per region (active/inactive).
2. Exact alert levels:
   - RED: Missile threat / mass-strike / ballistics
   - YELLOW: Drone (Shahed) threat / enhanced vigilance
   - ARTILLERY: Artillery / MLRS shelling threat
   - PARTIAL: Alarms in specific raions or hromadas
   - CLEAR: All clear / no alarm
3. Affected raions and duration (since XX:XX, ongoing for X h Y min).
4. Direct operational threat messages from Ukrainian Air Force (@kpszsu) & War Monitor (@war_monitor).
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import re
import time
import urllib.request
from zoneinfo import ZoneInfo

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))


SINGLE_DRONE_PATTERNS = [
    re.compile(r"\b1\s*х?\s*(?:бпла|дрон|шахед|безпілотник)", re.IGNORECASE),
    re.compile(r"\b(один|поодинокий|одиночний)\s*(?:бпла|дрон|шахед|безпілотник)", re.IGNORECASE),
    re.compile(r"\b(останній|залишив?ся\s+1|залишив?ся\s+один)\b", re.IGNORECASE),
    re.compile(r"\bдорозвідк\w*", re.IGNORECASE),
]

GROUP_DRONE_PATTERNS = [
    re.compile(r"\b(груп[аие]|декілька\s+груп|кілька\s+груп|чергова\s+група)\b", re.IGNORECASE),
    re.compile(r"\b([2-9]|\d{2,})\s*х?\s*(?:бпла|дрон|шахед|безпілотник)", re.IGNORECASE),
    re.compile(r"\b(декілька|кілька|багато|масован\w+|хвил[яі]|табун|рій)\s*(?:бпла|дрон|шахед|безпілотник)?", re.IGNORECASE),
]


class AlertsInUaLiveClient:
    """Live parser for alerts.in.ua sitrep feed with shared class-level cache TTL."""

    FEED_URL = "https://alerts.in.ua/llm"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AirAlertsBot/2.0"

    _shared_cached_text: Optional[str] = None
    _shared_last_fetch_time: float = 0.0

    def __init__(self, cache_ttl_seconds: int = 15):
        self.cache_ttl = cache_ttl_seconds

    def fetch_live_sitrep(self, force_refresh: bool = False) -> str:
        """Fetches live situation report text from alerts.in.ua with caching."""
        now = time.time()
        if not force_refresh and AlertsInUaLiveClient._shared_cached_text and (now - AlertsInUaLiveClient._shared_last_fetch_time < self.cache_ttl):
            return AlertsInUaLiveClient._shared_cached_text

        req = urllib.request.Request(self.FEED_URL, headers={"User-Agent": self.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read().decode("utf-8")
                AlertsInUaLiveClient._shared_cached_text = text
                AlertsInUaLiveClient._shared_last_fetch_time = now
                return text
        except Exception as e:
            if AlertsInUaLiveClient._shared_cached_text:
                return AlertsInUaLiveClient._shared_cached_text
            raise RuntimeError(f"Failed to fetch alerts.in.ua: {e}")

    def get_kyiv_time(self) -> datetime:
        """Returns current Kyiv local time."""
        return datetime.now(KYIV_TZ)

    def get_region_status(
        self,
        region_search_keys: List[str],
        region_name: str,
        raion_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Extracts live alert status for a specific region from alerts.in.ua sitrep."""
        text = self.fetch_live_sitrep()
        kyiv_time = self.get_kyiv_time()

        # Section 3: Current Warning Status
        sec3_match = re.search(r"## 3\. CURRENT WARNING STATUS(.*?)(?=## 4|\Z)", text, re.S)
        sec3 = sec3_match.group(1) if sec3_match else ""

        # Section 4: Threat Activity
        sec4_match = re.search(r"## 4\. THREAT ACTIVITY(.*?)(?=## 5|\Z)", text, re.S)
        sec4 = sec4_match.group(1) if sec4_match else ""

        # Section 6: Last Threat Messages
        sec6_match = re.search(r"## 6\. LAST THREAT MESSAGES.*?\n(.*?)(?=## 7|\Z)", text, re.S)
        sec6 = sec6_match.group(1) if sec6_match else ""

        # Section 8: Recent Warning Terminations
        sec8_match = re.search(r"## 8\. RECENT WARNING TERMINATIONS(.*?)(?=## 9|\Z)", text, re.S)
        sec8 = sec8_match.group(1) if sec8_match else ""

        # Parse recent terminations
        recent_terminations: Dict[str, str] = {}
        for line in sec8.splitlines():
            line = line.strip()
            tm = re.search(r"\*\*([0-9:]+—[0-9:]+)\*\*\s*(?:\(([^)]+)\))?\s*—\s*(.*)", line)
            if tm:
                time_range = tm.group(1)
                dur = tm.group(2) or ""
                details = tm.group(3)
                end_time = time_range.split("—")[-1].strip()
                dur_str = f" (тривала {dur})" if dur else ""
                if raion_names:
                    for r in raion_names:
                        r_stem = re.sub(r"\s+(район|місто|м\.)", "", r, flags=re.I).strip()
                        r_stem = re.sub(r"(ський|цький|зький|івський|овський)$", "", r_stem, flags=re.I)
                        if len(r_stem) >= 3 and r_stem.lower() in details.lower():
                            if r not in recent_terminations:
                                recent_terminations[r] = f"Відбій о {end_time}{dur_str}"

        # 1. Check Nominal alerts in occupied territory (АР Крим, Луганська область, Севастополь)
        nom_match = re.search(r"\*\*Nominal alerts in occupied territory\*\*\s*—\s*([^\n]+)", sec3, re.IGNORECASE)
        nom_text = nom_match.group(1) if nom_match else ""
        is_nominal_territory = False
        if nom_text and any(k in nom_text.lower() for k in region_search_keys):
            is_nominal_territory = True
        elif any(k in region_name.lower() for k in ["крим", "севастополь", "луганськ"]):
            is_nominal_territory = True

        if is_nominal_territory:
            raions_list = []
            if raion_names:
                for r in raion_names:
                    raions_list.append({
                        "name": r,
                        "status": "Постійна номінальна тривога (Окупована територія)",
                        "badge": "🔴",
                        "type": "NOMINAL",
                        "active": True,
                    })

            return {
                "region_name": region_name,
                "is_alert": True,
                "alert_level": "NOMINAL",
                "badge": "🔴 НОМІНАЛЬНА ТРИВОГА (ОКУПОВАНА ТЕРИТОРІЯ)",
                "color_emoji": "🔴",
                "status_text": "🔴 <b>Номінальна тривога:</b> діє безперервно для тимчасово окупованої території. Оголошена адміністративно (понад 1400 днів).",
                "duration_info": "Триває безперервно з 2022 р. (понад 1400 днів)",
                "affected_areas": "Увесь регіон під постійною номінальною тривогою",
                "raions": raions_list,
                "live_threats": self._find_threats_for_region(region_search_keys, sec4, sec6),
                "timestamp": kyiv_time,
            }

        # 2. Find matching line in Section 3
        found_block = None
        for key in region_search_keys:
            # Pattern matching: **Region Name (Укр)** — details
            pattern = rf"\*\*([^*]*{re.escape(key)}[^*]*)\*\*\s*—\s*([^\n]+(?:\n(?!\*\*)[^\n]+)*)"
            match = re.search(pattern, sec3, re.IGNORECASE)
            if match:
                found_block = (match.group(1).strip(), match.group(2).strip())
                break

        if not found_block:
            # No active warning for this region
            raions_list = []
            if raion_names:
                for r in raion_names:
                    if r in recent_terminations:
                        raions_list.append({
                            "name": r,
                            "status": recent_terminations[r],
                            "badge": "🟢",
                            "type": "CLEAR_RECENT",
                            "active": False,
                        })
                    else:
                        raions_list.append({
                            "name": r,
                            "status": "Спокійно (без тривоги)",
                            "badge": "🟢",
                            "type": "CLEAR",
                            "active": False,
                        })

            return {
                "region_name": region_name,
                "is_alert": False,
                "alert_level": "CLEAR",
                "badge": "🟢 ВІДБІЙ (СПОКІЙНО)",
                "color_emoji": "🟢",
                "status_text": "🟢 Тривога відсутня. Сирени не лунають.",
                "duration_info": "",
                "affected_areas": "Вся область спокійна",
                "raions": raions_list,
                "live_threats": self._find_threats_for_region(region_search_keys, sec4, sec6),
                "timestamp": kyiv_time,
            }

        header, body = found_block
        is_yellow = "yellow" in body.lower()
        is_artillery = "artillery" in body.lower() and "air raid" not in body.lower()
        has_artillery_and_air = "artillery" in body.lower() and "air raid" in body.lower()

        # Parse alert level
        if is_yellow:
            alert_level = "YELLOW"
            badge = "🟡 ЖОВТИЙ РІВЕНЬ (ЗАГРОЗА БпЛА)"
            color_emoji = "🟡"
            status_text = "🟡 <b>Жовтий рівень тривоги:</b> зафіксовано загрозу ворожих ударних БпЛА."
            default_raion_status = "Жовтий рівень (Загроза БпЛА)"
            default_badge = "🟡"
        elif is_artillery:
            alert_level = "ARTILLERY"
            badge = "🟠 ЗАГРОЗА АРТОБСТРІЛУ"
            color_emoji = "🟠"
            status_text = "🟠 <b>Артилерійська небезпека:</b> загроза ударів ствольної артилерії або РСЗВ."
            default_raion_status = "Загроза артобстрілу"
            default_badge = "🟠"
        elif has_artillery_and_air:
            alert_level = "RED"
            badge = "🔴 ЧЕРВОНИЙ РІВЕНЬ (ТРИВОГА ТА АРТОБСТРІЛ)"
            color_emoji = "🔴"
            status_text = "🔴 <b>Червоний рівень тривоги:</b> повітряна тривога та загроза артилерійських обстрілів."
            default_raion_status = "Червоний рівень (Повітряна тривога / Обстріл)"
            default_badge = "🔴"
        else:
            alert_level = "RED"
            badge = "🔴 ЧЕРВОНИЙ РІВЕНЬ (ПОВІТРЯНА ТРИВОГА)"
            color_emoji = "🔴"
            status_text = "🔴 <b>Червоний рівень тривоги:</b> підвищена небезпека (ракети / балістика / масований удар). Прямуйте в укриття!"
            default_raion_status = "Червоний рівень (Ракетна небезпека / Удар)"
            default_badge = "🔴"

        # Extract duration: e.g. "ongoing for 3 h 55 min" or "since 12:50"
        duration_info = ""
        dur_m = re.search(r"ongoing for\s+([^\.\[]+)", body, re.IGNORECASE)
        since_m = re.search(r"since\s+([^\,\.]+)", body, re.IGNORECASE)
        if since_m:
            duration_info += f"Початок: з {since_m.group(1).strip()}"
        if dur_m:
            duration_info += f" (триває {dur_m.group(1).strip()})"

        # Extract affected areas
        affected_areas = ""
        # Match both "1 area affected:" and "X areas affected:" or "areas affected:"
        areas_m = re.search(r"areas?\s+affected:\s*(.+)", body, re.IGNORECASE)
        affected_areas_text = ""
        if areas_m:
            raw_areas = areas_m.group(1).strip()
            # If "The most recent" sentence follows, strip it from areas list
            raw_areas = re.split(r"\bThe\s+most\s+recent\b", raw_areas, flags=re.IGNORECASE)[0].strip()
            # Extract Ukrainian names in brackets e.g. (Конотопський)
            ukr_names = re.findall(r"\(([А-Яа-яіїєґІЇЄҐ0-9\s\'\.-]+)\)", raw_areas)
            if ukr_names:
                affected_areas = ", ".join(ukr_names)
            else:
                affected_areas = raw_areas
            affected_areas_text = raw_areas
        elif "м. київ" in region_name.lower():
            affected_areas = "м. Київ (усі райони)"

        # Check recent additions (e.g. "most recent to go under alert was Nikopolskyi (Нікопольський) at 13:17")
        recent_add_match = re.search(r"most recent to go under alert was\s+([^\.]+)\s+at\s+([0-9:]+)", body, re.IGNORECASE)
        recent_add_info: Dict[str, str] = {}
        if recent_add_match:
            recent_add_info[recent_add_match.group(1).lower()] = recent_add_match.group(2)

        raions_list = []
        if raion_names:
            for r in raion_names:
                r_clean = re.sub(r"\s+(район|місто|м\.)", "", r, flags=re.I).strip()
                r_stem = re.sub(r"(ський|цький|зький|івський|овський)$", "", r_clean, flags=re.I)
                if len(r_stem) < 3:
                    r_stem = re.sub(r"ий$", "", r_clean, flags=re.I)
                if len(r_stem) < 3:
                    r_stem = r_clean

                is_affected = False
                if not affected_areas_text:
                    # Entire region is under alert
                    is_affected = True
                elif len(r_stem) >= 3 and r_stem.lower() in affected_areas_text.lower():
                    is_affected = True
                elif "(" in r:  # Check aliases like (Берестинський), (Шептицький), (Самарівський)
                    alias_m = re.findall(r"\(([^)]+)\)", r)
                    for al in alias_m:
                        al_clean = re.sub(r"\s+(район|місто|м\.)", "", al, flags=re.I).strip()
                        al_stem = re.sub(r"(ський|цький|зький|івський|овський)$", "", al_clean, flags=re.I)
                        if len(al_stem) >= 3 and al_stem.lower() in affected_areas_text.lower():
                            is_affected = True
                            break

                if is_affected:
                    # Check if line differentiates red vs yellow for specific areas (e.g. Kharkiv)
                    r_type = alert_level
                    r_badge = default_badge
                    r_status = default_raion_status

                    if "red" in affected_areas_text.lower() and "yellow" in affected_areas_text.lower():
                        # Sub-parse semicolon parts
                        for sub_part in affected_areas_text.split(";"):
                            if len(r_stem) >= 3 and r_stem.lower() in sub_part.lower():
                                if "red" in sub_part.lower():
                                    r_type = "RED"
                                    r_badge = "🔴"
                                    r_status = "Червоний рівень (Повітряна тривога)"
                                elif "yellow" in sub_part.lower():
                                    r_type = "YELLOW"
                                    r_badge = "🟡"
                                    r_status = "Жовтий рівень (Загроза БпЛА)"
                                break

                    for k, t_str in recent_add_info.items():
                        if len(r_stem) >= 3 and r_stem.lower() in k:
                            r_status += f" (з {t_str})"
                            break
                    raions_list.append({
                        "name": r,
                        "status": r_status,
                        "badge": r_badge,
                        "type": r_type,
                        "active": True,
                    })
                else:
                    if r in recent_terminations:
                        raions_list.append({
                            "name": r,
                            "status": recent_terminations[r],
                            "badge": "🟢",
                            "type": "CLEAR_RECENT",
                            "active": False,
                        })
                    else:
                        raions_list.append({
                            "name": r,
                            "status": "Спокійно (без тривоги)",
                            "badge": "🟢",
                            "type": "CLEAR",
                            "active": False,
                        })

        return {
            "region_name": region_name,
            "is_alert": True,
            "alert_level": alert_level,
            "badge": badge,
            "color_emoji": color_emoji,
            "status_text": status_text,
            "duration_info": duration_info,
            "affected_areas": affected_areas or "Уся територія області",
            "raions": raions_list,
            "live_threats": self._find_threats_for_region(region_search_keys, sec4, sec6),
            "timestamp": kyiv_time,
        }

    def get_all_raions_live_status(
        self,
        all_regions_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Parses the alerts.in.ua sitrep and returns independent alert status for ALL raions of Ukraine.

        Guarantees that each raion operates independently: an alert in 1 raion of an oblast
        does NOT taint other raions in that oblast.
        """
        if all_regions_dict is None:
            from src.bot.interactive_bot import ALL_REGIONS
            all_regions_dict = ALL_REGIONS

        raions_map: Dict[str, Dict[str, Any]] = {}
        for reg_code, reg_meta in all_regions_dict.items():
            reg_name = reg_meta.get("name", reg_code)
            reg_keys = reg_meta.get("keys", [reg_name])
            r_names = reg_meta.get("raions", [])

            reg_status = self.get_region_status(reg_keys, reg_name, raion_names=r_names)
            for r_item in reg_status.get("raions", []):
                r_name = r_item.get("name")
                if r_name:
                    raions_map[r_name] = {
                        "name": r_name,
                        "region_name": reg_name,
                        "region_code": reg_code,
                        "level": r_item.get("type", "CLEAR"),
                        "active": r_item.get("active", False),
                        "status": r_item.get("status", "Спокійно"),
                        "badge": r_item.get("badge", "🟢"),
                        "duration_info": reg_status.get("duration_info", ""),
                    }
        return raions_map

    def _find_threats_for_region(self, search_keys: List[str], sec4: str, sec6: str) -> Dict[str, Any]:
        """Searches threat activity and Air Force messages for items relevant to region."""
        all_threat_lines = []
        for line in sec4.splitlines() + sec6.splitlines():
            line = line.strip()
            if line.startswith("-"):
                all_threat_lines.append(line[1:].strip())

        threats = {
            "shahed": {
                "active": False,
                "desc": "🟢 Активності не зафіксовано",
                "prob": 0.05,
                "scale_type": "none",
                "scale_title": "🟢 Активності БпЛА не зафіксовано",
                "detected_quantity_text": "Загроза відсутня",
            },
            "ballistics": {"active": False, "desc": "🟢 Загроза відсутня", "prob": 0.02},
            "aviation": {"active": False, "desc": "🟢 Пусків КАБ не виявлено", "prob": 0.03},
            "mig31": {"active": False, "desc": "🟢 Борти МіГ-31К на аеродромах", "prob": 0.01},
            "missile": {"active": False, "desc": "🟢 Пусків крилатих ракет немає", "prob": 0.02},
            "raw_messages": [],
        }

        # Check for nationwide alerts
        sec4_6_lower = (sec4 + " " + sec6).lower()

        # Ballistics
        if any(w in sec4_6_lower for w in ["ballistic", "балістик", "іскандер", "с-300", "с-400"]):
            threats["ballistics"]["active"] = True
            threats["ballistics"]["desc"] = "🔴 <b>БАЛІСТИЧНА ЗАГРОЗА</b>: фіксація пусків або загрози застосування ОТРК"
            threats["ballistics"]["prob"] = 0.85

        # MiG-31K
        if any(w in sec4_6_lower for w in ["mig-31", "міг-31", "kinzhal", "кинджал", "саваслейк"]):
            threats["mig31"]["active"] = True
            threats["mig31"]["desc"] = "🔴 <b>Зліт МіГ-31К</b>: ракетна небезпека по всій території України"
            threats["mig31"]["prob"] = 0.90

        # Drones with scale detection (Single vs Group)
        if any(w in sec4_6_lower for w in ["drone", "бпла", "шахед", "uav", "безпілот"]):
            threats["shahed"]["active"] = True
            is_group = any(p.search(sec4_6_lower) for p in GROUP_DRONE_PATTERNS)
            is_single = any(p.search(sec4_6_lower) for p in SINGLE_DRONE_PATTERNS)
            if is_group:
                threats["shahed"]["scale_type"] = "group"
                threats["shahed"]["scale_title"] = "🚨 Група БпЛА (декілька цілей / хвиля)"
                threats["shahed"]["desc"] = "🚨 <b>ГРУПА ДРОНІВ</b>: ешелонована або масована атака (орієнтовно 1–2+ години)"
                threats["shahed"]["prob"] = 0.85
            else:
                threats["shahed"]["scale_type"] = "single"
                threats["shahed"]["scale_title"] = "⚠️ Поодинокий БпЛА (1 дрон)"
                threats["shahed"]["desc"] = "⚠️ <b>ПООДИНОКИЙ ДРОН (1 БпЛА)</b>: швидкісний транзит / локальна робота ППО (15–30 хв)"
                threats["shahed"]["prob"] = 0.65

        # Strategic aviation / cruise missiles
        if any(w in sec4_6_lower for w in ["ту-95", "ту-22", "калібр", "х-101", "х-59", "х-69", "cruise missile"]):
            threats["missile"]["active"] = True
            threats["missile"]["desc"] = "🔴 <b>РАКЕТНА НЕБЕЗПЕКА</b>: крилаті ракети / стратегічна авіація"
            threats["missile"]["prob"] = 0.80

        # Targeted search for this region in messages
        for line in all_threat_lines:
            line_lower = line.lower()
            if any(k in line_lower for k in search_keys):
                threats["raw_messages"].append(line)
                if any(w in line_lower for w in ["drone", "бпла", "шахед", "uav"]):
                    if any(p.search(line_lower) for p in GROUP_DRONE_PATTERNS):
                        threats["shahed"]["scale_type"] = "group"
                        threats["shahed"]["scale_title"] = "🚨 Група БпЛА над областю"
                        threats["shahed"]["desc"] = f"🚨 <b>ГРУПА ДРОНІВ НАД ОБЛАСТЮ</b>: {line[:120]}"
                    else:
                        threats["shahed"]["scale_type"] = "single"
                        threats["shahed"]["scale_title"] = "⚠️ Поодинокий БпЛА (1 дрон) над областю"
                        threats["shahed"]["desc"] = f"⚠️ <b>ПООДИНОКИЙ ДРОН (1 БпЛА)</b>: {line[:120]}"
                if any(w in line_lower for w in ["ballistic", "балістик", "іскандер"]):
                    threats["ballistics"]["desc"] = f"🔴 <b>БАЛІСТИКА ПО РЕГІОНУ</b>: {line[:120]}"

        return threats
