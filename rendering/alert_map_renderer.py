import io
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

from src.ingestion.alerts_live_client import AlertsInUaLiveClient, KYIV_TZ
from src.ingestion.neptun_client import NeptunClient
from src.ingestion.dimap_client import DimapClient
from src.bot.border_filter import is_point_in_ukraine


class AlertMapRenderer:
    """Renders visual tactical maps of Ukraine showing raion alert levels and drone vector projections."""

    def __init__(self, geojson_path: Optional[str] = None):
        if not geojson_path:
            geojson_path = str(Path(__file__).resolve().parents[1] / "data" / "ukraine_raions.geojson")
        self.geojson_path = geojson_path
        with open(self.geojson_path, "r", encoding="utf-8") as f:
            self.geojson = json.load(f)

    def render_map(
        self,
        horizon_minutes: int = 60,
        highlight_raion: Optional[str] = None,
        output_file: Optional[str] = None,
        cached_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Renders live tactical map of Ukraine and returns PNG bytes."""
        now_kyiv = datetime.now(KYIV_TZ)
        now_str = now_kyiv.strftime("%H:%M:%S (%d.%m.%Y)")
        target_str = (now_kyiv + datetime.resolution * 0).strftime("%H:%M") # placeholder

        # 1. Gather live data (use warm in-memory cache if available, else fetch)
        if cached_snapshot and cached_snapshot.get("is_warm"):
            alerts_raions = cached_snapshot.get("alerts_raions", {})
            classified = cached_snapshot.get("classified_drones", {})
            confirmed_threats = classified.get("confirmed_threats", [])
            probable_threats = classified.get("probable_threats", [])
            confirmed_count = classified.get("confirmed_count", 0)
            probable_count = classified.get("probable_count", 0)
            total_drones = classified.get("total_count", 0)
            nep_alerts = cached_snapshot.get("nep_alerts", {})
            dimap_alerts = cached_snapshot.get("dimap_alerts", [])
        else:
            alerts_client = AlertsInUaLiveClient()
            neptun = NeptunClient()
            dimap = DimapClient()

            # Ground-truth raion alerts from alerts.in.ua
            alerts_raions = {}
            try:
                alerts_raions = alerts_client.get_all_raions_live_status()
            except Exception:
                pass

            # Classified drones from Neptun (radar verified vs probable/acoustic)
            threats = neptun.get_threats()
            classified = neptun.classify_drones(threats)
            confirmed_threats = classified["confirmed_threats"]
            probable_threats = classified["probable_threats"]
            confirmed_count = classified["confirmed_count"]
            probable_count = classified["probable_count"]
            total_drones = classified["total_count"]

            # Radar and crowdsourced raion alerts
            nep_alerts = neptun.get_alerts()
            dimap_alerts = dimap.get_alerts()

        # Build independent raion status dictionary strictly from alerts.in.ua (Ground Truth)
        raion_levels: Dict[str, str] = {}
        for r_full_name, r_info in alerts_raions.items():
            r_clean = r_full_name.lower().replace(" район", "").strip()
            if r_info.get("active"):
                raion_levels[r_clean] = r_info.get("level", "YELLOW").upper()

        # Setup Matplotlib figure
        fig, ax = plt.subplots(figsize=(15, 9), dpi=140)
        fig.patch.set_facecolor("#0b0f19")
        ax.set_facecolor("#0b0f19")

        # Ukraine bounds
        ax.set_xlim(21.8, 40.5)
        ax.set_ylim(44.1, 52.5)
        ax.set_aspect(1.35)
        ax.axis("off")

        # Palette
        COLOR_CLEAR = "#111827"
        COLOR_CLEAR_BORDER = "#1f2937"
        COLOR_YELLOW = "#ca8a04"
        COLOR_YELLOW_BORDER = "#eab308"
        COLOR_RED = "#b91c1c"
        COLOR_RED_BORDER = "#ef4444"
        COLOR_NOMINAL = "#4c0519"
        COLOR_NOMINAL_BORDER = "#831843"
        COLOR_HIGHLIGHT = "#38bdf8"

        red_count = 0
        yellow_count = 0

        RAION_ALIASES = {
            "володимир-волинський": "володимирський",
            "новоград-волинський": "звягельський",
        }

        # Draw all 137 raion polygons strictly independently
        for feat in self.geojson.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            r_name = props.get("rayon", "")
            r_lower = r_name.lower().replace(" район", "").strip()
            if r_lower in RAION_ALIASES:
                r_lower = RAION_ALIASES[r_lower]

            # Determine alert status
            is_nominal = any(w in r_lower for w in ["крим", "севастополь", "луганськ", "донецьк"])
            matched_level = None

            if "київ" in r_lower:
                for k, v in alerts_raions.items():
                    if "київ" in v.get("region_name", "").lower() and v.get("active"):
                        matched_level = v.get("level", "YELLOW")
                        break
            else:
                for k, lvl in raion_levels.items():
                    if r_lower in k or k in r_lower:
                        matched_level = lvl
                        break

            if is_nominal and not matched_level:
                face = COLOR_NOMINAL
                edge = COLOR_NOMINAL_BORDER
                lw = 0.6
                alpha = 0.65
            elif matched_level == "RED":
                face = COLOR_RED
                edge = COLOR_RED_BORDER
                lw = 0.85
                alpha = 0.75
                red_count += 1
            elif matched_level == "YELLOW":
                face = COLOR_YELLOW
                edge = COLOR_YELLOW_BORDER
                lw = 0.85
                alpha = 0.70
                yellow_count += 1
            else:
                face = COLOR_CLEAR
                edge = COLOR_CLEAR_BORDER
                lw = 0.4
                alpha = 0.90

            is_highlighted = False
            if highlight_raion and (highlight_raion.lower() in r_name.lower() or r_name.lower() in highlight_raion.lower()):
                is_highlighted = True
                edge = COLOR_HIGHLIGHT
                lw = 2.4

            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            polys = [coords] if gtype == "Polygon" else (coords if gtype == "MultiPolygon" else [])

            for poly in polys:
                if len(poly) > 0:
                    ring = np.array(poly[0])
                    patch = patches.Polygon(
                        ring,
                        closed=True,
                        facecolor=face,
                        edgecolor=edge,
                        linewidth=lw,
                        alpha=alpha,
                        zorder=2 if not is_highlighted else 5,
                    )
                    ax.add_patch(patch)

        # Map border frame to prevent any element appearing outside Ukraine boundaries
        border_box = patches.Rectangle(
            (21.9, 44.15),
            40.4 - 21.9,
            52.45 - 44.15,
            linewidth=1.0,
            edgecolor="#334155",
            facecolor="none",
            linestyle="--",
            alpha=0.6,
            zorder=3,
        )
        ax.add_patch(border_box)

        # 2. Draw active drones categorized into 3 Threat Tiers (Red / Orange / Yellow)
        # Clamped strictly within Ukraine borders [44.40..52.35 N, 22.15..40.15 E]
        UKRAINE_MIN_LAT, UKRAINE_MAX_LAT = 44.38, 52.35
        UKRAINE_MIN_LON, UKRAINE_MAX_LON = 22.15, 40.15

        drone_speed_kmh = 180.0
        # Capped tactical horizon (max 35-45 km to avoid crossing the entire country)
        dist_km = min(40.0, drone_speed_kmh * (horizon_minutes / 60.0))

        # Combine and classify threats:
        # Tier 1 (HIGH / Red #ef4444): Confirmed by radar / military
        # Tier 2 (MEDIUM / Orange #f97316): Probable groups (count > 1)
        # Tier 3 (LOW / Yellow #fbbf24): Single probable / acoustic detections
        all_threats = []
        for t in confirmed_threats:
            all_threats.append({**t, "tier": "HIGH", "color": "#ef4444"})
        for t in probable_threats:
            count = int(t.get("count", 1) or 1)
            tier = "MEDIUM" if count > 1 else "LOW"
            color = "#f97316" if count > 1 else "#fbbf24"
            all_threats.append({**t, "tier": tier, "color": color})

        for t in all_threats:
            lat = t.get("lat")
            lon = t.get("lon")
            if lat is None or lon is None:
                continue

            # Strict sovereign border filter: discard telemetry outside Ukraine (Black Sea / neighboring countries)
            if not is_point_in_ukraine(lat, lon):
                continue

            heading = t.get("heading")
            count = int(t.get("count", 1) or 1)
            color = t.get("color", "#ef4444")
            tier = t.get("tier", "HIGH")

            # Sleek tactical radar blip (No bulky text boxes!)
            marker_size = 7 if tier == "HIGH" else (6 if tier == "MEDIUM" else 5)
            ax.plot(lon, lat, marker="o", markersize=marker_size, color=color, zorder=12)
            ax.plot(lon, lat, marker="o", markersize=marker_size * 2, color=color, alpha=0.32, zorder=11)

            # Only show neat mini badge if group of drones (x2, x3...)
            if count > 1:
                ax.text(
                    lon + 0.08,
                    lat + 0.06,
                    f"x{count}",
                    color="#ffffff",
                    fontsize=7.0,
                    fontweight="bold",
                    zorder=14,
                    bbox=dict(boxstyle="round,pad=0.15", facecolor=color, edgecolor="#ffffff", alpha=0.90, linewidth=0.6),
                )

            # Extrapolation vector strictly clamped to Ukraine borders
            if heading is not None:
                heading_rad = math.radians(heading)
                d_lat = (dist_km * math.cos(heading_rad)) / 111.0
                d_lon = (dist_km * math.sin(heading_rad)) / (111.0 * math.cos(math.radians(lat)))

                target_lat = lat + d_lat
                target_lon = lon + d_lon

                # Clamp target strictly inside Ukraine borders
                target_lat = max(UKRAINE_MIN_LAT, min(UKRAINE_MAX_LAT, target_lat))
                target_lon = max(UKRAINE_MIN_LON, min(UKRAINE_MAX_LON, target_lon))

                # Draw clean trajectory line (NO duplicate dot at tip)
                linestyle = "-" if tier == "HIGH" else ("--" if tier == "MEDIUM" else ":")
                lw = 1.6 if tier == "HIGH" else 1.2
                ax.plot([lon, target_lon], [lat, target_lat], color=color, linestyle=linestyle, linewidth=lw, alpha=0.85, zorder=10)

        # Title & Subtitle Banner
        fig.text(0.04, 0.94, "КАРТА ПОВІТРЯНИХ ЗАГРОЗ ТА ВЕКТОРІВ БпЛА (РАЙОНИ УКРАЇНИ)", color="#f8fafc", fontsize=15, fontweight="bold")
        sub_text = (
            f"Оновлено о {now_str} • Горизонт: +{horizon_minutes} хв • "
            f"Всього БпЛА: {total_drones} (підтверджено: {confirmed_count}, ймовірні/дорозвідка: {probable_count})"
        )
        fig.text(0.04, 0.91, sub_text, color="#94a3b8", fontsize=9.2)

        # Legend Box
        legend_x = 0.04
        legend_y = 0.05
        leg_items = [
            ("● Червоний район", f"Офіційна повітряна/ракетна тривога ({red_count} районів)"),
            ("● Жовтий район", f"Загроза ударних дронів / БпЛА ({yellow_count} районів)"),
            ("● Червоний БпЛА", f"Висока загроза (радар ЗСУ) — {confirmed_count} од."),
            ("● Оранжевий / Жовтий", f"Ймовірні групи та розрахункові цілі — {probable_count} од."),
            ("── Вектор", "Курс БпЛА (вектори обмежені кордонами України)"),
        ]
        if highlight_raion:
            leg_items.append(("■ Блакитний контур", f"Ваш район: {highlight_raion}"))

        fig.text(legend_x, legend_y + 0.14, "ЛЕГЕНДА ЗАГРОЗ (НЕЗАЛЕЖНІ РАЙОНИ):", color="#e2e8f0", fontsize=9, fontweight="bold")
        for i, (tag, desc) in enumerate(leg_items):
            y_pos = legend_y + 0.11 - (i * 0.024)
            fig.text(legend_x, y_pos, f"• {tag}: ", color="#cbd5e1", fontsize=8.0, fontweight="bold")
            fig.text(legend_x + 0.14, y_pos, desc, color="#94a3b8", fontsize=8.0)

        # Save buffer
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.15, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        img_bytes = buf.getvalue()

        if output_file:
            with open(output_file, "wb") as f:
                f.write(img_bytes)

        return img_bytes


if __name__ == "__main__":
    renderer = AlertMapRenderer()
    out = str(Path(__file__).resolve().parents[1] / "rendering" / "live_threats_map.png")
    renderer.render_map(horizon_minutes=60, output_file=out)
    print(f"Generated live map: {out}")
