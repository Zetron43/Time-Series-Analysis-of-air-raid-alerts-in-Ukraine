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
import threading
import time
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))


class UserSubscriptionManager:
    """Thread-safe persistent manager for user raion alert subscriptions with auto-reload from disk."""

    _instances: Dict[str, "UserSubscriptionManager"] = {}
    _global_lock = threading.Lock()

    def __new__(cls, file_path: Optional[str] = None):
        if not file_path:
            file_path = str(Path(__file__).resolve().parents[2] / "data" / "user_subscriptions.json")
        norm_path = os.path.abspath(file_path)
        with cls._global_lock:
            if norm_path not in cls._instances:
                inst = super().__new__(cls)
                cls._instances[norm_path] = inst
            return cls._instances[norm_path]

    def __init__(self, file_path: Optional[str] = None):
        if hasattr(self, "_initialized") and self._initialized:
            self._check_reload()
            return
        if not file_path:
            file_path = str(Path(__file__).resolve().parents[2] / "data" / "user_subscriptions.json")
        self.file_path = os.path.abspath(file_path)
        self._lock = threading.RLock()
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._last_mtime: float = 0.0
        self._load()
        self._initialized = True

    def _check_reload(self):
        """Checks if the file on disk was modified by another thread/process and reloads it."""
        try:
            p = Path(self.file_path)
            if p.exists():
                mtime = p.stat().st_mtime
                if mtime > self._last_mtime:
                    self._load()
        except Exception:
            pass

    def _load(self):
        with self._lock:
            p = Path(self.file_path)
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        self._subscriptions = json.load(f)
                    self._last_mtime = p.stat().st_mtime
                except Exception:
                    self._subscriptions = {}
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                self._save()

    def _save(self):
        with self._lock:
            try:
                p = Path(self.file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                # Atomic file write: write to temp file then atomic replace to prevent corruption on crash
                tmp_path = p.with_name(f"{p.name}.tmp_{os.getpid()}_{threading.get_ident()}")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._subscriptions, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.file_path)
                if p.exists():
                    self._last_mtime = p.stat().st_mtime
            except Exception as e:
                print(f"[-] Error saving subscriptions atomically: {e}", flush=True)

    def add_subscription(self, chat_id: int | str, raion_name: str) -> bool:
        """Adds a raion to user's tracked list. Returns True if newly added."""
        self._check_reload()
        with self._lock:
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
        self._check_reload()
        with self._lock:
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
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            return list(self._subscriptions.get(cid, {}).get("raions", []))

    def set_home_raion(self, chat_id: int | str, raion_name: str, region_code: str = "", region_name: str = "") -> None:
        """Sets the primary/pinned home raion for 1-click quick access."""
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            if cid not in self._subscriptions:
                self._subscriptions[cid] = {
                    "raions": [],
                    "created_at": datetime.now(KYIV_TZ).isoformat(),
                    "last_notifications": {},
                }
            self._subscriptions[cid]["home_raion"] = {
                "raion": raion_name,
                "region_code": region_code,
                "region_name": region_name,
                "updated_at": datetime.now(KYIV_TZ).isoformat(),
            }
            # Also auto-subscribe to home raion
            raions = self._subscriptions[cid].get("raions", [])
            if raion_name not in raions:
                raions.append(raion_name)
                self._subscriptions[cid]["raions"] = raions
            self._save()

    def get_home_raion(self, chat_id: int | str) -> Optional[Dict[str, str]]:
        """Returns the user's pinned home raion if set."""
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            return self._subscriptions.get(cid, {}).get("home_raion")

    def clear_home_raion(self, chat_id: int | str) -> bool:
        """Removes the pinned home raion."""
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            if cid in self._subscriptions and "home_raion" in self._subscriptions[cid]:
                del self._subscriptions[cid]["home_raion"]
                self._save()
                return True
            return False

    def get_all_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """Returns all registered subscriptions."""
        self._check_reload()
        with self._lock:
            return dict(self._subscriptions)

    def should_notify(
        self,
        chat_id: int | str,
        raion_name: str,
        event_key: str,
        cooldown_minutes: int = 25,
    ) -> bool:
        """Determines if enough time has passed to send a specific notification event."""
        self._check_reload()
        with self._lock:
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
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            if cid in self._subscriptions:
                if "last_notifications" not in self._subscriptions[cid]:
                    self._subscriptions[cid]["last_notifications"] = {}
                note_id = f"{raion_name}::{event_key}"
                self._subscriptions[cid]["last_notifications"][note_id] = datetime.now(KYIV_TZ).isoformat()
                self._save()

    def set_alert_state(self, chat_id: int | str, raion_name: str, state: str):
        """Sets the last known active alert state for (chat_id, raion_name)."""
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            if cid in self._subscriptions:
                if "alert_states" not in self._subscriptions[cid]:
                    self._subscriptions[cid]["alert_states"] = {}
                self._subscriptions[cid]["alert_states"][raion_name] = state
                self._save()

    def get_alert_state(self, chat_id: int | str, raion_name: str) -> str:
        """Returns the last alert state ('OFFICIAL', 'WARNING', 'NEIGHBOR', 'CLEAR')."""
        self._check_reload()
        with self._lock:
            cid = str(chat_id)
            user_data = self._subscriptions.get(cid, {})
            return user_data.get("alert_states", {}).get(raion_name, "CLEAR")

    def had_active_alert(self, chat_id: int | str, raion_name: str) -> bool:
        """Checks if there was an active official alarm or warning previously recorded."""
        return self.get_alert_state(chat_id, raion_name) in ["OFFICIAL", "WARNING", "NEIGHBOR"]

    def clear_alert_state(self, chat_id: int | str, raion_name: str):
        """Clears the active alert state back to CLEAR."""
        self.set_alert_state(chat_id, raion_name, "CLEAR")


class AutoDeleteManager:
    """Manages scheduled automatic deletion of raion alarm messages after 1 hour (3600s)."""

    def __init__(self, file_path: Optional[str] = None):
        if not file_path:
            file_path = str(Path(__file__).resolve().parents[2] / "data" / "pending_message_deletions.json")
        self.file_path = file_path
        self._lock = threading.Lock()
        self._pending: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        p = Path(self.file_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self._pending = json.load(f)
            except Exception:
                self._pending = []
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            self._save()

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._pending, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[-] Error saving pending deletions: {e}", flush=True)

    def schedule_deletion(
        self,
        chat_id: int | str,
        message_id: int,
        delay_seconds: int = 3600,
        raion_name: str = "",
    ):
        """Schedules a message to be automatically deleted after delay_seconds (default 1 hour)."""
        delete_at = time.time() + delay_seconds
        with self._lock:
            self._pending.append({
                "chat_id": chat_id,
                "message_id": message_id,
                "delete_at": delete_at,
                "created_at": time.time(),
                "raion_name": raion_name,
            })
            self._save()

    def pop_previous_raion_alerts(self, chat_id: int | str, raion_name: str) -> List[int]:
        """Finds and removes prior un-deleted alert message IDs for this raion to replace them."""
        with self._lock:
            to_delete = []
            remaining = []
            for item in self._pending:
                if str(item.get("chat_id")) == str(chat_id) and item.get("raion_name") == raion_name:
                    to_delete.append(item.get("message_id"))
                else:
                    remaining.append(item)
            if to_delete:
                self._pending = remaining
                self._save()
            return to_delete

    def get_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._pending)

    def process_pending(self, api_caller_func) -> int:
        """Checks and deletes all messages whose 1-hour expiration timestamp has arrived."""
        now = time.time()
        deleted_count = 0
        with self._lock:
            if not self._pending:
                return 0

            remaining = []
            for item in self._pending:
                if now >= item.get("delete_at", 0):
                    cid = item.get("chat_id")
                    mid = item.get("message_id")
                    try:
                        api_caller_func("deleteMessage", {
                            "chat_id": cid,
                            "message_id": mid,
                        })
                        deleted_count += 1
                    except Exception:
                        pass
                else:
                    remaining.append(item)

            if len(remaining) != len(self._pending):
                self._pending = remaining
                self._save()

        return deleted_count

