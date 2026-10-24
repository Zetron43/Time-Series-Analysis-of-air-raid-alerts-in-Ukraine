"""Client for fetching live regional & raion air alert status from dimap.live.

Provides:
- Raion and city alerts with color-coded severity (red/yellow).
- Alert start timestamps.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import json
import ssl
import time
import urllib.request
from zoneinfo import ZoneInfo

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))


class DimapClient:
    """Client for dimap.live API with shared class-level caching."""

    BASE_URL = "https://api.dimap.live/api"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AirAlertsBot/2.5"

    _shared_cached_alerts: Optional[List[Dict[str, Any]]] = None
    _shared_last_alerts_time: float = 0.0

    def __init__(self, cache_ttl: int = 20):
        self.cache_ttl = cache_ttl
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def get_alerts(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns list of active alerts by raions/cities from dimap.live."""
        now = time.time()
        if not force_refresh and DimapClient._shared_cached_alerts and (now - DimapClient._shared_last_alerts_time < self.cache_ttl):
            return DimapClient._shared_cached_alerts

        url = f"{self.BASE_URL}/alerts"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw)
                if isinstance(data, list):
                    DimapClient._shared_cached_alerts = data
                    DimapClient._shared_last_alerts_time = now
                    return data
                return []
        except Exception:
            if DimapClient._shared_cached_alerts:
                return DimapClient._shared_cached_alerts
            return []

    def get_raion_status(self, raion_name: str) -> Optional[Dict[str, Any]]:
        """Finds alert status for a given raion in dimap.live data."""
        alerts = self.get_alerts()
        r_clean = raion_name.lower().replace(" район", "").strip()

        for a in alerts:
            reg = (a.get("region") or "").lower()
            if r_clean in reg or reg in r_clean:
                return a
        return None
