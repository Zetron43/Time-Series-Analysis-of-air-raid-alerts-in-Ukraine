"""Client for fetching live targets, drones (Shaheds), and raion alerts from neptun.in.ua.

Provides:
- Exact GPS coordinates of detected UAVs/missiles.
- Course / heading in degrees (0-360) and flight history trails.
- Drone counts (single drone vs group/cluster).
- Official and crowdsourced raion alert levels (yellow / red).
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import json
import math
import ssl
import time
import urllib.request
from zoneinfo import ZoneInfo

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))


class NeptunClient:
    """Client for neptun.in.ua API v1 with shared class-level caching."""

    BASE_URL = "https://neptun.in.ua/api/v1"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AirAlertsBot/2.5"

    _shared_cached_threats: Optional[Dict[str, Any]] = None
    _shared_last_threats_time: float = 0.0

    _shared_cached_alerts: Optional[Dict[str, Any]] = None
    _shared_last_alerts_time: float = 0.0

    def __init__(self, cache_ttl: int = 20):
        self.cache_ttl = cache_ttl
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _request_json(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw)

    def get_threats(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns list of active airborne targets (drones, missiles) with coordinates and courses."""
        now = time.time()
        if not force_refresh and NeptunClient._shared_cached_threats and (now - NeptunClient._shared_last_threats_time < self.cache_ttl):
            return NeptunClient._shared_cached_threats.get("threats", [])

        try:
            data = self._request_json("threats")
            NeptunClient._shared_cached_threats = data
            NeptunClient._shared_last_threats_time = now
            return data.get("threats", [])
        except Exception as exc:
            if NeptunClient._shared_cached_threats:
                return NeptunClient._shared_cached_threats.get("threats", [])
            return []

    def get_alerts(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns active alerts by raions and oblasts from neptun.in.ua."""
        now = time.time()
        if not force_refresh and NeptunClient._shared_cached_alerts and (now - NeptunClient._shared_last_alerts_time < self.cache_ttl):
            return NeptunClient._shared_cached_alerts

        try:
            data = self._request_json("alerts")
            NeptunClient._shared_cached_alerts = data
            NeptunClient._shared_last_alerts_time = now
            return data
        except Exception:
            if NeptunClient._shared_cached_alerts:
                return NeptunClient._shared_cached_alerts
            return {"raions": [], "oblasts": []}

    @staticmethod
    def is_threat_confirmed(threat: Dict[str, Any]) -> bool:
        """Determines if a threat is confirmed by radar/sensors vs probable/presumed.

        Confirmed criteria:
        - positionQuality is 'confirmed' or lifecycle is 'confirmed'
        - OR high confidence level with 2+ sources and not presumptive course
        """
        pos_quality = str(threat.get("positionQuality", "")).lower()
        lifecycle = str(threat.get("lifecycle", "")).lower()
        if pos_quality == "confirmed" or lifecycle == "confirmed":
            return True

        presumptive = bool(threat.get("presumptiveCourse", False))
        if presumptive:
            return False

        confidence = str(threat.get("confidenceLevel", "")).lower()
        source_count = int(threat.get("sourceCount", 1) or 1)
        if confidence == "high" and source_count >= 2:
            return True

        return False

    def classify_drones(self, threats: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Classifies drone threats into confirmed (verified radar) vs probable (presumed/acoustic/scout).

        Returns counts and separate lists of threats.
        """
        if threats is None:
            threats = self.get_threats()

        uav_threats = [t for t in threats if t.get("type", "uav") in ["uav", "shahed", "drone", "fpv"]]

        confirmed_list: List[Dict[str, Any]] = []
        probable_list: List[Dict[str, Any]] = []

        confirmed_count = 0
        probable_count = 0

        for t in uav_threats:
            item = dict(t)
            count = int(item.get("count", 1) or 1)
            if self.is_threat_confirmed(item):
                item["certainty"] = "confirmed"
                item["certainty_label"] = "Підтверджений (радар)"
                confirmed_list.append(item)
                confirmed_count += count
            else:
                item["certainty"] = "probable"
                item["certainty_label"] = "Ймовірний / дорозвідка"
                probable_list.append(item)
                probable_count += count

        return {
            "all_uavs": uav_threats,
            "confirmed_threats": confirmed_list,
            "probable_threats": probable_list,
            "confirmed_count": confirmed_count,
            "probable_count": probable_count,
            "total_count": confirmed_count + probable_count,
            "total_targets": len(uav_threats),
        }

    def get_raion_threat_summary(self, raion_name: str) -> Dict[str, Any]:
        """Summarizes drone and alert threats for a specific raion with certainty classification."""
        threats = self.get_threats()
        alerts_data = self.get_alerts()

        # Check alert level in Neptun
        raion_clean = raion_name.lower().replace(" район", "").strip()
        matched_alert = None
        for a in alerts_data.get("raions", []):
            a_name = a.get("name", "").lower()
            if raion_clean in a_name or a_name in raion_clean:
                matched_alert = a
                break

        # Check UAVs located in or heading towards this raion
        local_uavs = []
        for t in threats:
            t_reg = (t.get("region") or "").lower()
            t_dist = (t.get("district") or "").lower()
            t_loc = (t.get("locality") or "").lower()

            is_in_raion = (raion_clean in t_dist) or (raion_clean in t_loc)
            if is_in_raion:
                local_uavs.append(t)

        classified_all = self.classify_drones(threats)
        classified_local = self.classify_drones(local_uavs)

        return {
            "has_neptun_alert": matched_alert is not None,
            "neptun_level": matched_alert.get("level", "clear") if matched_alert else "clear",
            "neptun_reasons": matched_alert.get("reasons", []) if matched_alert else [],
            "neptun_since": matched_alert.get("since") if matched_alert else None,
            "local_drones": local_uavs,
            "local_confirmed_count": classified_local["confirmed_count"],
            "local_probable_count": classified_local["probable_count"],
            "local_confirmed_drones": classified_local["confirmed_threats"],
            "local_probable_drones": classified_local["probable_threats"],
            "total_active_drones_countrywide": classified_all["total_count"],
            "total_confirmed_countrywide": classified_all["confirmed_count"],
            "total_probable_countrywide": classified_all["probable_count"],
        }
