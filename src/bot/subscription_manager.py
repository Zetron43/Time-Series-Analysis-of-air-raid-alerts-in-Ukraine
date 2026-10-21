"""User subscription manager for automatic raion-level alerts and early warnings.

Manages:
1. Subscribed raions per chat_id.
2. Notification state and cooldown tracking (to avoid duplicate spam).
3. Persistent storage in data/user_subscriptions.json.
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))


class UserSubscriptionManager:
    """Thread-safe persistent manager for user raion alert subscriptions."""

    def __init__(self, file_path: Optional[str] = None):
        if not file_path:
            file_path = str(Path(__file__).resolve().parents[2] / "data" / "user_subscriptions.json")
        self.file_path = file_path
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        p = Path(self.file_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self._subscriptions = json.load(f)
            except Exception:
                self._subscriptions = {}
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            self._save()

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._subscriptions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[-] Error saving subscriptions: {e}", flush=True)

    def add_subscription(self, chat_id: int | str, raion_name: str) -> bool:
        """Adds a raion to user's tracked list. Returns True if newly added."""
        cid = str(chat_id)
        if cid not in self._subscriptions:
            self._subscriptions[cid] = {
                "raions": [],
                "created_at": datetime.now(KYIV_TZ).isoformat(),
                "last_notifications": {},
            }

        raions = self._subscriptions[cid].get("raions", [])
        if raion_name not in raions:
            raions.append(raion_name)
            self._subscriptions[cid]["raions"] = raions
            self._save()
            return True
        return False

    def remove_subscription(self, chat_id: int | str, raion_name: str) -> bool:
        """Removes a raion from user's tracked list."""
        cid = str(chat_id)
        if cid in self._subscriptions:
            raions = self._subscriptions[cid].get("raions", [])
            if raion_name in raions:
                raions.remove(raion_name)
                self._subscriptions[cid]["raions"] = raions
                self._save()
                return True
        return False

    def get_user_subscriptions(self, chat_id: int | str) -> List[str]:
        """Returns list of tracked raions for a specific user."""
        cid = str(chat_id)
        return list(self._subscriptions.get(cid, {}).get("raions", []))

    def get_all_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """Returns all registered subscriptions."""
        return self._subscriptions

    def should_notify(
        self,
        chat_id: int | str,
        raion_name: str,
        event_key: str,
        cooldown_minutes: int = 25,
    ) -> bool:
        """Determines if enough time has passed to send a specific notification event."""
        cid = str(chat_id)
        user_data = self._subscriptions.get(cid, {})
        last_notes = user_data.get("last_notifications", {})

        note_id = f"{raion_name}::{event_key}"
        last_time_str = last_notes.get(note_id)

        now = datetime.now(KYIV_TZ)
        if not last_time_str:
            return True

        try:
            last_dt = datetime.fromisoformat(last_time_str)
            if (now - last_dt) > timedelta(minutes=cooldown_minutes):
                return True
            return False
        except Exception:
            return True

    def mark_notified(self, chat_id: int | str, raion_name: str, event_key: str):
        """Marks that a notification was dispatched at current time."""
        cid = str(chat_id)
        if cid in self._subscriptions:
            if "last_notifications" not in self._subscriptions[cid]:
                self._subscriptions[cid]["last_notifications"] = {}
            note_id = f"{raion_name}::{event_key}"
            self._subscriptions[cid]["last_notifications"][note_id] = datetime.now(KYIV_TZ).isoformat()
            self._save()
