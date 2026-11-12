"""Multi-Source Data Fusion Consensus Engine.

Enforces cross-validation rule (≥ 2 independent sources required for high alert confirmation):
Sources:
1. alerts.in.ua (Official Civil Protection siren state)
2. neptun.in.ua (Dron Alerts radar sensor feed)
3. dimap.live (Real-time collaborative radar tracking)
4. @kpszsu (Air Force Command Telegram tactical warnings)

Eliminates spoofing and single-sensor electronic warfare (EW/РЕБ) false alarms.
"""

from typing import Dict, Any, List, Set, Optional


class MultiSourceConsensusVerifier:
    """Verifies target authenticity and threat level across multiple independent sources."""

    @staticmethod
    def verify_raion_consensus(
        raion_name: str,
        is_official_alert: bool = False,
        radar_threats_present: bool = False,
        dimap_alert_present: bool = False,
        osint_warning_present: bool = False,
        radar_confirmed_flag: bool = False,
    ) -> Dict[str, Any]:
        """Checks multi-source consensus for a given raion.

        Returns detailed consensus status dict.
        """
        active_sources: List[str] = []

        if is_official_alert:
            active_sources.append("alerts.in.ua (Офіційні сирени)")

        if radar_threats_present or radar_confirmed_flag:
            active_sources.append("neptun.in.ua (Радарна телеметрія)")

        if dimap_alert_present:
            active_sources.append("dimap.live (Радарна карта)")

        if osint_warning_present:
            active_sources.append("КПС ЗСУ (Тактичний моніторинг)")

        consensus_count = len(active_sources)
        is_consensus = consensus_count >= 2

        if consensus_count >= 2:
            status = "CONFIRMED_CONSENSUS"
            badge = f"🟢 Верифіковано консенсусом ({consensus_count} джерел)"
            recommendation = "Загроза підтверджена кількома незалежними системами. Слідуйте в укриття."
        elif consensus_count == 1:
            status = "PROBABLE_SINGLE_SOURCE"
            badge = f"🟡 Одиничне джерело ({active_sources[0]})"
            recommendation = "Зафіксовано поодиноким датчиком. Триває крос-валідація, зберігайте пильність."
        else:
            status = "CLEAR"
            badge = "⚪ Спокійно (0 активних джерел)"
            recommendation = "Прямих загроз не зафіксовано."

        return {
            "raion": raion_name,
            "sources_count": consensus_count,
            "active_sources": active_sources,
            "is_consensus_verified": is_consensus,
            "status": status,
            "badge": badge,
            "recommendation": recommendation,
        }

    @staticmethod
    def verify_uav_track(
        threat_dict: Dict[str, Any],
        official_alerts_active_nearby: bool = False,
        tg_osint_active: bool = False,
    ) -> Dict[str, Any]:
        """Verifies individual airborne track against radar and OSINT signals."""
        sources: List[str] = []
        speed = float(threat_dict.get("speed_kmh", 180.0) or 180.0)

        # 1. Kinematic speed check (EW spoofing filter: > 900 km/h)
        if speed > 900.0:
            return {
                "is_valid": False,
                "is_consensus_verified": False,
                "reason": "REB_SPOOFING_SPEED_EXCEEDED",
                "badge": "⛔ Відхилено: Аномальна швидкість РЕБ (>900 км/год)",
            }

        # 2. Check source agreement
        sources.append("Радарний первинний трек (Neptun)")

        pos_quality = str(threat_dict.get("positionQuality", "")).lower()
        source_count = int(threat_dict.get("sourceCount", 1) or 1)
        if pos_quality == "confirmed" or source_count >= 2:
            sources.append("Вторинне радарне підтвердження")

        if official_alerts_active_nearby:
            sources.append("Співпадіння із зоною тривоги alerts.in.ua")

        if tg_osint_active:
            sources.append("Оперативне зведення Повітряних Сил")

        is_consensus = len(sources) >= 2
        return {
            "is_valid": True,
            "sources_count": len(sources),
            "sources": sources,
            "is_consensus_verified": is_consensus,
            "badge": (
                f"🟢 Консенсус: {len(sources)} джерела" if is_consensus else "🟡 Одиничний трек (перевіряється)"
            ),
        }
