"""Lightweight WebApp HTTP Server for Telegram Mini App & Live Tactical Map.

Serves:
1. GET / -> rendering/webapp/index.html (Telegram WebApp UI)
2. GET /api/geojson -> data/ukraine_raions.geojson
3. GET /api/threats -> live JSON with active raion alert levels and drone vector data
4. GET /api/eta?raion=<name> -> instant kinematic ETA calculation for target raion
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


class WebAppRequestHandler(BaseHTTPRequestHandler):
    """Handles static WebApp files and dynamic JSON threat API."""

    def log_message(self, format, *args):
        # Silence normal request logs to keep bot console clean
        pass

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
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "WebApp index.html not found")
                return

        # 2. GeoJSON boundaries
        if path == "/api/geojson":
            global _CACHED_GEOJSON_BYTES
            if _CACHED_GEOJSON_BYTES:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(_CACHED_GEOJSON_BYTES)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(_CACHED_GEOJSON_BYTES)
                return
            elif GEOJSON_PATH.exists():
                with open(GEOJSON_PATH, "rb") as f:
                    _CACHED_GEOJSON_BYTES = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(_CACHED_GEOJSON_BYTES)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(_CACHED_GEOJSON_BYTES)
                return
            self.send_error(404, "GeoJSON not found")
            return

        # 3. Live threats & raion levels
        if path == "/api/threats":
            snap = syncer.state.get_snapshot()
            alerts_raions = snap["alerts_raions"]
            raion_levels = {}
            for r_full, info in alerts_raions.items():
                if info.get("active"):
                    r_clean = r_full.lower().replace(" район", "").strip()
                    raion_levels[r_clean] = info.get("level", "YELLOW").upper()

            # Supplement with Neptun radar warnings
            for item in snap["nep_alerts"].get("raions", []):
                r_clean = item.get("name", "").lower().replace(" район", "").strip()
                if r_clean not in raion_levels:
                    raion_levels[r_clean] = item.get("level", "yellow").upper()

            # Supplement with Dimap alerts
            for item in snap["dimap_alerts"]:
                r_clean = item.get("region", "").lower().replace(" район", "").strip()
                lvl = "RED" if item.get("color") == "red" else "YELLOW"
                if r_clean not in raion_levels or lvl == "RED":
                    raion_levels[r_clean] = lvl

            threats = snap["raw_threats"]
            payload = {
                "updated_at": snap["last_updated"].isoformat() if snap["last_updated"] else None,
                "drones_count": len(threats),
                "raion_levels": raion_levels,
                "drones": threats[:30],
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        # 4. Live raion ETA lookup
        if path == "/api/eta":
            query = urllib.parse.parse_qs(parsed.query)
            raion_name = query.get("raion", [""])[0]
            calc = KinematicETACalculator()
            snap = syncer.state.get_snapshot()
            eta_res = calc.calculate_eta_for_raion(raion_name, snap["raw_threats"])
            body = json.dumps(eta_res, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
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
