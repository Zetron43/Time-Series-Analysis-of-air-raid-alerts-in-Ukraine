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
    ) -> bytes:
        """Renders live tactical map of Ukraine and returns PNG bytes."""
        now_kyiv = datetime.now(KYIV_TZ)
        now_str = now_kyiv.strftime("%H:%M:%S (%d.%m.%Y)")
        target_str = (now_kyiv + datetime.resolution * 0).strftime("%H:%M") # placeholder

        # 1. Gather live data
        neptun = NeptunClient()
        dimap = DimapClient()

        threats = neptun.get_threats()
        nep_alerts = neptun.get_alerts()
        dimap_alerts = dimap.get_alerts()

        # Build raion status dictionary
        raion_levels: Dict[str, str] = {}

        # Fill from neptun
        for item in nep_alerts.get("raions", []):
            r_name = item.get("name", "").strip().lower()
            lvl = item.get("level", "yellow").upper()
            raion_levels[r_name] = lvl

        # Fill from dimap
        for item in dimap_alerts:
            reg = item.get("region", "").strip().lower()
            color = item.get("color", "red").upper()
            lvl = "RED" if color == "RED" else "YELLOW"
            if reg not in raion_levels or lvl == "RED":
                raion_levels[reg] = lvl

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

        # Draw all raion polygons
        for feat in self.geojson.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            r_name = props.get("rayon", "")
            r_lower = r_name.lower().replace(" район", "").strip()

            # Determine alert status
            is_nominal = any(w in r_lower for w in ["крим", "севастополь", "луганськ", "донецьк"])
            matched_level = None

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
                lw = 0.8
                alpha = 0.75
                red_count += 1
            elif matched_level == "YELLOW":
                face = COLOR_YELLOW
                edge = COLOR_YELLOW_BORDER
                lw = 0.8
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
                lw = 2.2

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

        # 2. Draw active drones and forecast vectors
        drone_speed_kmh = 180.0
        dist_km = drone_speed_kmh * (horizon_minutes / 60.0)
        active_uavs = 0

        for t in threats:
            lat = t.get("lat")
            lon = t.get("lon")
            if lat is None or lon is None:
                continue

            active_uavs += 1
            heading = t.get("heading")
            count = t.get("count") or 1

            # Current position marker
            ax.plot(lon, lat, marker="o", markersize=7, color="#ef4444", zorder=10)
            ax.plot(lon, lat, marker="o", markersize=14, color="#ef4444", alpha=0.35, zorder=9)

            # Annotation text
            count_label = f" x{count}" if count > 1 else ""
            ax.text(
                lon + 0.08,
                lat + 0.06,
                f"БпЛА{count_label}",
                color="#ffffff",
                fontsize=7.5,
                fontweight="bold",
                zorder=12,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#1e1e2f", edgecolor="#ef4444", alpha=0.85, linewidth=0.6),
            )

            # Draw vector if heading is available
            if heading is not None:
                heading_rad = math.radians(heading)
                d_lat = (dist_km * math.cos(heading_rad)) / 111.0
                d_lon = (dist_km * math.sin(heading_rad)) / (111.0 * math.cos(math.radians(lat)))

                target_lat = lat + d_lat
                target_lon = lon + d_lon

                # Vector line
                ax.plot([lon, target_lon], [lat, target_lat], color="#f43f5e", linestyle="--", linewidth=1.4, alpha=0.85, zorder=8)

                # Future position halo
                horizon_label = f"+{horizon_minutes}хв" if horizon_minutes < 60 else f"+{horizon_minutes//60}г"
                ax.plot(target_lon, target_lat, marker="x", markersize=6, color="#f43f5e", zorder=10)
                circle = patches.Circle((target_lon, target_lat), radius=0.20, color="#f43f5e", fill=True, alpha=0.15, zorder=7)
                ax.add_patch(circle)
                ax.text(
                    target_lon + 0.05,
                    target_lat - 0.08,
                    horizon_label,
                    color="#fca5a5",
                    fontsize=7,
                    fontweight="bold",
                    zorder=11,
                )

        # Title & Subtitle Banner
        fig.text(0.04, 0.94, "КАРТА ПОВІТРЯНИХ ЗАГРОЗ ТА ВЕКТОРІВ БпЛА УКРАЇНИ", color="#f8fafc", fontsize=15, fontweight="bold")
        sub_text = f"Оновлено о {now_str} • Горизонт екстраполяції: +{horizon_minutes} хв (швидкість дрона ~{int(drone_speed_kmh)} км/год)"
        fig.text(0.04, 0.91, sub_text, color="#94a3b8", fontsize=9.5)

        # Legend Box
        legend_x = 0.04
        legend_y = 0.06
        leg_items = [
            ("● Червоний", "Ракетна/повітряна тривога"),
            ("● Жовтий", "Загроза ударних дронів (БпЛА)"),
            ("▲ Маркер", f"Позиція цілі (активно {active_uavs} БпЛА)"),
            ("--> Пунктир", f"Прогноз положення через {horizon_minutes} хв"),
        ]
        if highlight_raion:
            leg_items.append(("■ Контур", f"Ваш район: {highlight_raion}"))

        fig.text(legend_x, legend_y + 0.12, "ЛЕГЕНДА ЗАГРОЗ:", color="#e2e8f0", fontsize=9, fontweight="bold")
        for i, (tag, desc) in enumerate(leg_items):
            y_pos = legend_y + 0.09 - (i * 0.026)
            fig.text(legend_x, y_pos, f"• {tag}: ", color="#cbd5e1", fontsize=8.2, fontweight="bold")
            fig.text(legend_x + 0.10, y_pos, desc, color="#94a3b8", fontsize=8.2)

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
