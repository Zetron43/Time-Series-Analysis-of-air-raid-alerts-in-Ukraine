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
import json
import os
from pathlib import Path
import threading
from typing import Optional
import urllib.parse

from src.bot.threat_state_manager import get_threat_syncer
from src.bot.eta_calculator import KinematicETACalculator
from src.bot.subscription_manager import UserSubscriptionManager

BASE_DIR = Path(__file__).resolve().parents[2]
WEBAPP_HTML_PATH = BASE_DIR / "rendering" / "webapp" / "index.html"
GEOJSON_PATH = BASE_DIR / "data" / "ukraine_raions.geojson"

# Pre-load GeoJSON in memory for ultra-fast serving
_CACHED_GEOJSON_BYTES: Optional[bytes] = None
if GEOJSON_PATH.exists():
    try:
        with open(GEOJSON_PATH, "rb") as f:
            _CACHED_GEOJSON_BYTES = f.read()
    except Exception as e:
        print(f"[WebAppServer] Error reading GeoJSON: {e}")

_sub_manager = UserSubscriptionManager()


class WebAppRequestHandler(BaseHTTPRequestHandler):
    """Handles static WebApp files and dynamic JSON threat API."""

    def log_message(self, format, *args):
        # Silence normal request logs to keep bot console clean
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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
                    r_clean = r_full.lower().replace(" район", "").strip()
                    raion_levels[r_clean] = info.get("level", "YELLOW").upper()

            # Supplement with Neptun radar warnings
            for item in snap.get("nep_alerts", {}).get("raions", []):
                r_clean = item.get("name", "").lower().replace(" район", "").strip()
                if r_clean not in raion_levels:
                    raion_levels[r_clean] = item.get("level", "yellow").upper()

            # Supplement with Dimap alerts
            for item in snap.get("dimap_alerts", []):
                r_clean = item.get("region", "").lower().replace(" район", "").strip()
                lvl = "RED" if item.get("color") == "red" else "YELLOW"
                if r_clean not in raion_levels or lvl == "RED":
                    raion_levels[r_clean] = lvl

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
                # Discard any noise/telemetry outside Ukrainian borders (e.g. far into Black Sea or Moldova/Romania)
                if f_lat < 44.38 or f_lat > 52.38 or f_lon < 22.14 or f_lon > 40.22:
                    continue
                if f_lon < 28.0 and f_lat < 47.9 and not (f_lon >= 25.0 and f_lat >= 47.9) and not (f_lon >= 28.5 and f_lat <= 45.6):
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
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        try:
            self._server = HTTPServer((self.host, self.port), WebAppRequestHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="WebAppServer")
            self._thread.start()
            print(f"[+] Telegram WebApp Server started on http://{self.host}:{self.port}/", flush=True)
        except Exception as e:
            print(f"[-] Could not bind WebApp Server on port {self.port}: {e}", flush=True)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            print("[+] WebApp Server stopped.", flush=True)
