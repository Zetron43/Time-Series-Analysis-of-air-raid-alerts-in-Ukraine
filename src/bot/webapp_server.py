"""Lightweight WebApp HTTP Server for Telegram Mini App & Live Tactical Map.

Serves:
1. GET / -> rendering/webapp/index.html (Telegram WebApp UI)
2. GET /api/geojson -> data/ukraine_raions.geojson
3. GET /api/threats -> live JSON with active raion alert levels and classified drone blips
4. GET /api/eta?raion=<name> -> instant kinematic ETA and threat analysis
5. GET /api/regions -> all macro-zones, regions and raions tree
6. GET /api/user?chat_id=<id> -> user's pinned home raion and subscriptions
7. POST /api/set_home -> sets pinned home raion
8. POST /api/toggle_sub -> toggles subscription for raion
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import os
import re
from pathlib import Path
import threading
from typing import Optional
import urllib.parse

from src.bot.threat_state_manager import get_threat_syncer
from src.bot.eta_calculator import KinematicETACalculator
from src.bot.subscription_manager import UserSubscriptionManager
from src.bot.border_filter import is_point_in_ukraine

BASE_DIR = Path(__file__).resolve().parents[2]
WEBAPP_HTML_PATH = BASE_DIR / "rendering" / "webapp" / "index.html"
if not WEBAPP_HTML_PATH.exists():
    candidate_html = BASE_DIR / "Time Series Analysis of air raid alerts in Ukraine" / "rendering" / "webapp" / "index.html"
    if candidate_html.exists():
        WEBAPP_HTML_PATH = candidate_html

# Robust lookup for GeoJSON
GEOJSON_PATH = BASE_DIR / "data" / "ukraine_raions.geojson"
if not GEOJSON_PATH.exists():
    candidate_geo = BASE_DIR / "Time Series Analysis of air raid alerts in Ukraine" / "data" / "ukraine_raions.geojson"
    if candidate_geo.exists():
        GEOJSON_PATH = candidate_geo

# Pre-load GeoJSON in memory for ultra-fast serving
_CACHED_GEOJSON_BYTES: Optional[bytes] = None
if GEOJSON_PATH.exists():
    try:
        with open(GEOJSON_PATH, "rb") as f:
            _CACHED_GEOJSON_BYTES = f.read()
    except Exception as e:
        print(f"[WebAppServer] Error reading GeoJSON: {e}")

_sub_manager = UserSubscriptionManager()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """High-concurrency HTTP server executing each client request in a separate thread."""
    daemon_threads = True
    allow_reuse_address = True


class WebAppRequestHandler(BaseHTTPRequestHandler):
    """Handles static WebApp files and dynamic JSON threat API."""

    def log_message(self, format, *args):
        # Silence normal request logs to keep bot console clean
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_no_cache_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        syncer = get_threat_syncer()

        # 1. Main WebApp page
        if path in ["/", "/index.html", "/webapp"]:
            if WEBAPP_HTML_PATH.exists():
                with open(WEBAPP_HTML_PATH, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_cors_headers()
                self.send_no_cache_headers()
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "WebApp index.html not found")
                return

        # 2. GeoJSON boundaries
        if path == "/api/geojson":
            global _CACHED_GEOJSON_BYTES
            if not _CACHED_GEOJSON_BYTES and GEOJSON_PATH.exists():
                with open(GEOJSON_PATH, "rb") as f:
                    _CACHED_GEOJSON_BYTES = f.read()
            if _CACHED_GEOJSON_BYTES:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(_CACHED_GEOJSON_BYTES)))
                self.send_cors_headers()
                self.send_no_cache_headers()
                self.end_headers()
                self.wfile.write(_CACHED_GEOJSON_BYTES)
                return
            self.send_error(404, "GeoJSON not found")
            return

        # 3. Live threats & classified drones
        if path == "/api/threats":
            snap = syncer.state.get_snapshot()
            alerts_raions = snap.get("alerts_raions", {})
            raion_levels = {}
            for r_full, info in alerts_raions.items():
                if info.get("active"):
                    lvl = info.get("level", "YELLOW").upper()
                    r_clean = r_full.lower().replace(" район", "").strip()
                    raion_levels[r_clean] = lvl
                    base_name = re.sub(r"\(.*?\)", "", r_clean).strip()
                    if base_name:
                        raion_levels[base_name] = lvl
                    parens = re.findall(r"\((.*?)\)", r_clean)
                    for p in parens:
                        p_clean = p.strip()
                        if p_clean:
                            raion_levels[p_clean] = lvl

            # Standard canonical aliases for renamed raions
            RAION_ALIASES = {
                "володимир-волинський": "володимирський",
                "новоград-волинський": "звягельський",
                "червоноградський": "шептицький",
                "новомосковський": "самарівський",
                "красноградський": "берестинський",
            }
            for alias, target in RAION_ALIASES.items():
                if target in raion_levels and alias not in raion_levels:
                    raion_levels[alias] = raion_levels[target]

            threats = snap.get("raw_threats", [])
            classified = snap.get("classified_drones", {})
            active_alarms_count = sum(1 for lvl in raion_levels.values() if lvl == "RED")

            # Format sleek drone blips
            drones_clean = []
            for t in threats:
                lat = t.get("lat")
                lon = t.get("lon")
                if lat is None or lon is None:
                    continue
                try:
                    f_lat = float(lat)
                    f_lon = float(lon)
                except (ValueError, TypeError):
                    continue

                # Strict Ukraine sovereign boundary filter:
                # Discard any noise/telemetry outside Ukrainian land borders (e.g. far into Black Sea or Moldova/Romania)
                if not is_point_in_ukraine(f_lat, f_lon):
                    continue

                is_conf = bool(t.get("is_confirmed") or t.get("lifecycle") == "confirmed")
                count = int(t.get("count", 1) or 1)
                heading = t.get("heading")
                
                # Assign tier: HIGH (red), MEDIUM (orange), LOW (yellow)
                if is_conf:
                    tier = "HIGH"
                    color = "#ef4444"
                elif count > 1:
                    tier = "MEDIUM"
                    color = "#f97316"
                else:
                    tier = "LOW"
                    color = "#fbbf24"

                drones_clean.append({
                    "lat": f_lat,
                    "lon": f_lon,
                    "heading": heading,
                    "count": count,
                    "is_confirmed": is_conf,
                    "tier": tier,
                    "color": color,
                    "speed_kmh": float(t.get("speed", 180.0) or 180.0),
                    "locality": t.get("locality") or "",
                    "region": t.get("region") or "",
                    "title": t.get("title") or "Шахед",
                    "updated_at": t.get("updatedAt") or "",
                })

            payload = {
                "updated_at": snap["last_updated"].isoformat() if snap.get("last_updated") else None,
                "drones_count": len(drones_clean),
                "confirmed_count": classified.get("confirmed_count", sum(1 for d in drones_clean if d["is_confirmed"])),
                "probable_count": classified.get("probable_count", sum(1 for d in drones_clean if not d["is_confirmed"])),
                "active_alarms_count": active_alarms_count,
                "raion_levels": raion_levels,
                "drones": drones_clean,
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.send_no_cache_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # 4. Live raion ETA and analysis lookup
        if path == "/api/eta":
            query = urllib.parse.parse_qs(parsed.query)
            raion_name = query.get("raion", [""])[0]
            calc = KinematicETACalculator()
            snap = syncer.state.get_snapshot()
            eta_res = calc.calculate_eta_for_raion(raion_name, snap.get("raw_threats", []))
            body = json.dumps(eta_res, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.send_no_cache_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # 5. Full regions & raions hierarchy
        if path == "/api/regions":
            try:
                from src.bot.interactive_bot import ALL_REGIONS, MACRO_ZONES
                payload = {
                    "macro_zones": MACRO_ZONES,
                    "regions": ALL_REGIONS,
                }
            except Exception as e:
                payload = {"error": str(e)}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.send_no_cache_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # 6. User pinned home and tracked raions
        if path == "/api/user":
            query = urllib.parse.parse_qs(parsed.query)
            chat_id = query.get("chat_id", [""])[0]
            home_raion = _sub_manager.get_home_raion(chat_id) if chat_id else None
            subs = _sub_manager.get_user_subscriptions(chat_id) if chat_id else []
            payload = {
                "chat_id": chat_id,
                "home_raion": home_raion,
                "subscriptions": subs,
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.send_no_cache_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404, "Path not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            payload = {}

        chat_id = str(payload.get("chat_id", ""))
        raion_name = str(payload.get("raion", "")).strip()

        if path == "/api/set_home":
            if chat_id and raion_name:
                from src.bot.interactive_bot import ALL_REGIONS
                r_code, reg_name = "kyiv_obl", "Київська область"
                for reg_k, reg_v in ALL_REGIONS.items():
                    for rn in reg_v.get("raions", []):
                        if rn.lower() == raion_name.lower():
                            r_code, reg_name = reg_k, reg_v.get("name", reg_k)
                            break
                _sub_manager.set_home_raion(chat_id, raion_name, region_code=r_code, region_name=reg_name)
                resp_data = {"ok": True, "home_raion": _sub_manager.get_home_raion(chat_id)}

                # Synchronize notification back to Telegram chat
                token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
                if token:
                    try:
                        from src.bot.interactive_bot import telegram_api_call
                        telegram_api_call(token, "sendMessage", {
                            "chat_id": chat_id,
                            "text": (
                                f"⭐ <b>Ваш «Мій район» оновлено через веб-мапу:</b>\n\n"
                                f"📍 <b>{raion_name}</b> ({reg_name})\n"
                                f"🔔 Автоматичне слідкування та ранні сповіщення для цього району активовано.\n"
                                f"Для швидкого перегляду в 1 клік використовуйте кнопку «⭐ Мій район» у головному меню чату."
                            ),
                            "parse_mode": "HTML",
                        })
                    except Exception as e:
                        print(f"[WebAppServer] Error sending set_home chat sync message: {e}")
            else:
                resp_data = {"ok": False, "error": "Missing chat_id or raion"}

            body = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/toggle_sub":
            if chat_id and raion_name:
                user_subs = _sub_manager.get_user_subscriptions(chat_id)
                if raion_name in user_subs:
                    _sub_manager.remove_subscription(chat_id, raion_name)
                    is_sub = False
                else:
                    _sub_manager.add_subscription(chat_id, raion_name)
                    is_sub = True
                resp_data = {
                    "ok": True,
                    "subscribed": is_sub,
                    "subscriptions": _sub_manager.get_user_subscriptions(chat_id),
                }

                # Synchronize notification back to Telegram chat
                token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
                if token:
                    try:
                        from src.bot.interactive_bot import telegram_api_call
                        if is_sub:
                            sub_text = (
                                f"🔔 <b>Підписку активовано через веб-мапу:</b>\n\n"
                                f"📍 <b>{raion_name}</b>\n"
                                f"Бот надсилатиме вам миттєві сповіщення при появі загроз або наближенні БпЛА до цього району."
                            )
                        else:
                            sub_text = f"🔕 <b>Підписку вимкнено через веб-мапу:</b>\n\n📍 <b>{raion_name}</b>"
                        telegram_api_call(token, "sendMessage", {
                            "chat_id": chat_id,
                            "text": sub_text,
                            "parse_mode": "HTML",
                        })
                    except Exception as e:
                        print(f"[WebAppServer] Error sending toggle_sub chat sync message: {e}")
            else:
                resp_data = {"ok": False, "error": "Missing chat_id or raion"}

            body = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/send_to_chat":
            if chat_id and raion_name:
                token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TOKEN")
                if token:
                    try:
                        from src.bot.interactive_bot import (
                            ALL_REGIONS,
                            ThreatAnalyzer,
                            format_interactive_forecast_response,
                            get_raion_horizon_keyboard,
                            telegram_api_call,
                        )
                        clean_r = raion_name.lower().replace(" район", "").strip()
                        found_region_code = "kyiv_obl"
                        for reg_code, reg_info in ALL_REGIONS.items():
                            for rn in reg_info.get("raions", []):
                                if rn.lower().replace(" район", "").strip() == clean_r:
                                    found_region_code = reg_code
                                    break
                            if found_region_code != "kyiv_obl":
                                break

                        raions_list = ALL_REGIONS.get(found_region_code, {}).get("raions", [])
                        r_idx = raions_list.index(raion_name) if raion_name in raions_list else 0

                        analyzer = ThreatAnalyzer()
                        res = analyzer.analyze_threats_for_region(found_region_code, "60m", raion_name=raion_name)
                        reply_text = format_interactive_forecast_response(res)
                        kb = get_raion_horizon_keyboard(found_region_code, r_idx)

                        send_res = telegram_api_call(token, "sendMessage", {
                            "chat_id": chat_id,
                            "text": reply_text,
                            "parse_mode": "HTML",
                            "reply_markup": kb,
                        })
                        resp_data = {"ok": send_res.get("ok", False)}
                    except Exception as e:
                        print(f"[-] /api/send_to_chat error: {e}", flush=True)
                        resp_data = {"ok": False, "error": str(e)}
                else:
                    resp_data = {"ok": False, "error": "Bot token not available"}
            else:
                resp_data = {"ok": False, "error": "Missing chat_id or raion"}

            body = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404, "Path not found")


class WebAppServer:
    """Threaded web server manager."""

    def __init__(self, port: int = 8080, host: str = "0.0.0.0"):
        self.port = int(os.environ.get("PORT", port))
        self.host = host
        self._server: Optional[ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        try:
            self._server = ThreadedHTTPServer((self.host, self.port), WebAppRequestHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="WebAppServer")
            self._thread.start()
            print(f"[+] Multi-threaded WebApp Server started on http://{self.host}:{self.port}/", flush=True)
        except Exception as e:
            print(f"[-] Could not bind WebApp Server on port {self.port}: {e}", flush=True)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            print("[+] WebApp Server stopped.", flush=True)
