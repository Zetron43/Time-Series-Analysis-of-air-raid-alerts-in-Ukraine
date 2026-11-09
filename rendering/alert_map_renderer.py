import io
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

from src.ingestion.alerts_live_client import AlertsInUaLiveClient, KYIV_TZ
from src.ingestion.neptun_client import NeptunClient
from src.ingestion.dimap_client import DimapClient
from src.bot.border_filter import is_point_in_ukraine
from src.bot.eta_calculator import KinematicETACalculator


def point_to_segment_dist_km(plat: float, plon: float, lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float]:
    """Computes perpendicular distance from point to flight segment and distance along segment in km."""
    cos_lat = math.cos(math.radians((lat1 + lat2 + plat) / 3.0))
    x1, y1 = lon1 * 111.0 * cos_lat, lat1 * 111.0
    x2, y2 = lon2 * 111.0 * cos_lat, lat2 * 111.0
    px, py = plon * 111.0 * cos_lat, plat * 111.0

    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.hypot(px - x1, py - y1), 0.0

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    dist = math.hypot(px - proj_x, py - proj_y)
    dist_along = t * math.sqrt(seg_len_sq)
    return dist, dist_along


class AlertMapRenderer:
    """Renders dynamic tactical maps of Ukraine showing live alerts, drone vectors, and projected threat horizons."""

    def __init__(self, geojson_path: Optional[str] = None):
        if not geojson_path:
            p1 = Path(__file__).resolve().parents[1] / "data" / "ukraine_raions.geojson"
            if p1.exists():
                geojson_path = str(p1)
            else:
                p2 = Path(__file__).resolve().parents[2] / "data" / "ukraine_raions.geojson"
                geojson_path = str(p2)
        self.geojson_path = geojson_path
        with open(self.geojson_path, "r", encoding="utf-8") as f:
            self.geojson = json.load(f)
        self.eta_calc = KinematicETACalculator()

    def render_map(
        self,
        horizon_minutes: int = 60,
        highlight_raion: Optional[str] = None,
        output_file: Optional[str] = None,
        cached_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Renders live tactical map of Ukraine for the specified horizon and returns PNG bytes."""
        now_kyiv = datetime.now(KYIV_TZ)
        now_str = now_kyiv.strftime("%H:%M:%S (%d.%m.%Y)")
        target_time_str = (now_kyiv + timedelta(minutes=horizon_minutes)).strftime("%H:%M")

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
            if not r_info.get("active"):
                continue
            lvl = r_info.get("level", "YELLOW").upper()
            r_clean = r_full_name.lower().replace(" район", "").strip()
            raion_levels[r_clean] = lvl
            base_name = re.sub(r"\(.*?\)", "", r_clean).strip()
            if base_name:
                raion_levels[base_name] = lvl
            parens = re.findall(r"\((.*?)\)", r_clean)
            for p in parens:
                p_clean = p.strip()
                if p_clean:
                    raion_levels[p_clean] = lvl

        # 2. Build Threat Tiers and Extrapolate Trajectories for this exact horizon
        UKRAINE_MIN_LAT, UKRAINE_MAX_LAT = 44.38, 52.35
        UKRAINE_MIN_LON, UKRAINE_MAX_LON = 22.15, 40.15

        all_threats = []
        for t in confirmed_threats:
            all_threats.append({**t, "tier": "HIGH", "color": "#ef4444"})
        for t in probable_threats:
            count = int(t.get("count", 1) or 1)
            tier = "MEDIUM" if count > 1 else "LOW"
            color = "#f97316" if count > 1 else "#fbbf24"
            all_threats.append({**t, "tier": tier, "color": color})

        drone_speed_kmh = 180.0
        # Dynamic flight distance in km traveled during horizon_minutes
        dist_km = drone_speed_kmh * (horizon_minutes / 60.0)

        computed_trajectories = []
        for t in all_threats:
            lat = t.get("lat")
            lon = t.get("lon")
            if lat is None or lon is None:
                continue
            if not is_point_in_ukraine(lat, lon):
                continue

            heading = t.get("heading")
            speed = float(t.get("speed_kmh") or drone_speed_kmh)
            count = int(t.get("count", 1) or 1)
            tier = t.get("tier", "HIGH")
            color = t.get("color", "#ef4444")

            traj = {
                "lat": lat,
                "lon": lon,
                "heading": heading,
                "speed": speed,
                "count": count,
                "tier": tier,
                "color": color,
                "dist_km": dist_km,
                "has_vector": False,
                "target_lat": None,
                "target_lon": None,
            }

            if heading is not None:
                heading_rad = math.radians(heading)
                d_lat = (dist_km * math.cos(heading_rad)) / 111.0
                d_lon = (dist_km * math.sin(heading_rad)) / (111.0 * math.cos(math.radians(lat)))

                t_lat = max(UKRAINE_MIN_LAT, min(UKRAINE_MAX_LAT, lat + d_lat))
                t_lon = max(UKRAINE_MIN_LON, min(UKRAINE_MAX_LON, lon + d_lon))

                traj["target_lat"] = t_lat
                traj["target_lon"] = t_lon
                traj["has_vector"] = True

            computed_trajectories.append(traj)

        # 3. Identify Threatened Raions along the flight corridor for this horizon (ETA <= horizon_minutes)
        projected_raions: Dict[str, float] = {}  # clean_raion_name -> min_eta_minutes
        for r_clean, centroid in self.eta_calc.centroids.items():
            r_lat, r_lon = centroid
            for tr in computed_trajectories:
                if tr["has_vector"]:
                    p_dist, p_along = point_to_segment_dist_km(
                        r_lat, r_lon, tr["lat"], tr["lon"], tr["target_lat"], tr["target_lon"]
                    )
                    # Tactical corridor width: 32 km from flight axis
                    if p_dist <= 32.0 and p_along <= tr["dist_km"]:
                        eta_calc = (p_along / tr["speed"]) * 60.0
                        if eta_calc <= horizon_minutes:
                            if r_clean not in projected_raions or eta_calc < projected_raions[r_clean]:
                                projected_raions[r_clean] = eta_calc
                else:
                    # Radial alert for targets with unspecified heading
                    rad_dist = math.hypot((r_lat - tr["lat"]) * 111.0, (r_lon - tr["lon"]) * 111.0 * math.cos(math.radians(r_lat)))
                    if rad_dist <= min(35.0, dist_km):
                        eta_calc = (rad_dist / tr["speed"]) * 60.0
                        if eta_calc <= horizon_minutes:
                            if r_clean not in projected_raions or eta_calc < projected_raions[r_clean]:
                                projected_raions[r_clean] = eta_calc

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
        COLOR_PROJECTED = "#c2410c"          # Burnt amber for forecasted corridor
        COLOR_PROJECTED_BORDER = "#f97316"   # Bright orange border
        COLOR_NOMINAL = "#4c0519"
        COLOR_NOMINAL_BORDER = "#831843"
        COLOR_HIGHLIGHT = "#38bdf8"

        red_count = 0
        yellow_count = 0
        projected_count = 0

        RAION_ALIASES = {
            "володимир-волинський": "володимирський",
            "новоград-волинський": "звягельський",
            "червоноградський": "шептицький",
            "новомосковський": "самарівський",
            "красноградський": "берестинський",
        }

        # 4. Draw all 137 raion polygons with multi-tier threat classification
        for feat in self.geojson.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            r_name = props.get("rayon", "")
            r_lower = r_name.lower().replace(" район", "").strip()

            is_nominal = any(w in r_lower for w in ["крим", "севастополь", "луганськ", "донецьк"])
            matched_level = None

            if "київ" in r_lower:
                for k, v in alerts_raions.items():
                    if "київ" in v.get("region_name", "").lower() and v.get("active"):
                        matched_level = v.get("level", "YELLOW")
                        break
            else:
                if r_lower in raion_levels:
                    matched_level = raion_levels[r_lower]
                else:
                    canon = RAION_ALIASES.get(r_lower, r_lower)
                    if canon in raion_levels:
                        matched_level = raion_levels[canon]

            # Priority 1: Official Siren (Red)
            if matched_level == "RED":
                face = COLOR_RED
                edge = COLOR_RED_BORDER
                lw = 0.85
                alpha = 0.78
                red_count += 1
            # Priority 2: Direct Threat / Live Siren (Yellow)
            elif matched_level == "YELLOW":
                face = COLOR_YELLOW
                edge = COLOR_YELLOW_BORDER
                lw = 0.85
                alpha = 0.72
                yellow_count += 1
            # Priority 3: Projected Threat on Flight Path (Orange)
            elif (r_lower in projected_raions or RAION_ALIASES.get(r_lower, r_lower) in projected_raions) and not is_nominal:
                face = COLOR_PROJECTED
                edge = COLOR_PROJECTED_BORDER
                lw = 1.15
                alpha = 0.75
                projected_count += 1
            # Priority 4: Nominal (Occupied regions)
            elif is_nominal and not matched_level:
                face = COLOR_NOMINAL
                edge = COLOR_NOMINAL_BORDER
                lw = 0.6
                alpha = 0.65
            # Priority 5: Clear
            else:
                face = COLOR_CLEAR
                edge = COLOR_CLEAR_BORDER
                lw = 0.4
                alpha = 0.90

            is_highlighted = False
            if highlight_raion:
                hl_clean = highlight_raion.lower().replace(" район", "").strip()
                hl_canon = RAION_ALIASES.get(hl_clean, hl_clean)
                if r_lower == hl_clean or r_lower == hl_canon:
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

        # Map border frame
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

        # 5. Draw active drones and dynamic trajectory routes
        for tr in computed_trajectories:
            lon, lat = tr["lon"], tr["lat"]
            color = tr["color"]
            tier = tr["tier"]
            count = tr["count"]

            marker_size = 7 if tier == "HIGH" else (6 if tier == "MEDIUM" else 5)
            # Radar blip
            ax.plot(lon, lat, marker="o", markersize=marker_size, color=color, zorder=12)
            ax.plot(lon, lat, marker="o", markersize=marker_size * 2, color=color, alpha=0.32, zorder=11)

            # Drone group count badge
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

            # Dynamic trajectory vector
            if tr["has_vector"]:
                target_lat = tr["target_lat"]
                target_lon = tr["target_lon"]

                linestyle = "-" if tier == "HIGH" else ("--" if tier == "MEDIUM" else ":")
                lw = 2.0 if tier == "HIGH" else 1.5

                # Main flight path
                ax.plot([lon, target_lon], [lat, target_lat], color=color, linestyle=linestyle, linewidth=lw, alpha=0.88, zorder=10)

                # Intermediate timeline ticks for horizons >= 30 min
                if horizon_minutes >= 30:
                    step_mins = 15 if horizon_minutes <= 60 else 30
                    cur_m = step_mins
                    while cur_m < horizon_minutes:
                        frac = cur_m / horizon_minutes
                        w_lat = lat + frac * (target_lat - lat)
                        w_lon = lon + frac * (target_lon - lon)
                        ax.plot(w_lon, w_lat, marker="+", markersize=5, color=color, alpha=0.75, zorder=11)
                        cur_m += step_mins

                # Projected endpoint marker at t + horizon_minutes
                ax.plot(target_lon, target_lat, marker="o", markersize=4.5, color=color, alpha=0.95, zorder=12)
                ax.plot(target_lon, target_lat, marker="o", markersize=9, fillstyle="none", color=color, alpha=0.65, linestyle=":", zorder=12)

                # Horizon badge at arrival tip
                h_tag = f"+{horizon_minutes}хв" if horizon_minutes < 60 else f"+{horizon_minutes//60}г"
                ax.text(
                    target_lon + 0.08,
                    target_lat - 0.05,
                    h_tag,
                    color=color,
                    fontsize=7.0,
                    fontweight="bold",
                    zorder=13,
                    bbox=dict(boxstyle="round,pad=0.12", facecolor="#0b131e", edgecolor=color, alpha=0.75, linewidth=0.5),
                )

        # Title & Subtitle Banner
        fig.text(0.04, 0.94, "КАРТА ПОВІТРЯНИХ ЗАГРОЗ ТА ВЕКТОРІВ БпЛА (РАЙОНИ УКРАЇНИ)", color="#f8fafc", fontsize=15, fontweight="bold")
        sub_text = (
            f"Оновлено о {now_str} • Горизонт: +{horizon_minutes} хв (до {target_time_str}) • "
            f"БпЛА: {total_drones} • На курсі підльоту: {projected_count} районів"
        )
        fig.text(0.04, 0.91, sub_text, color="#94a3b8", fontsize=9.2)

        # Legend Box
        legend_x = 0.04
        legend_y = 0.05
        leg_items = [
            ("● Червоний район", f"Офіційна повітряна/ракетна тривога ({red_count} районів)"),
            ("● Жовтий район", f"Поточна загроза БпЛА над районом ({yellow_count} районів)"),
            ("● Помаранчевий район", f"Прогнозована загроза підльоту (+{horizon_minutes} хв) ({projected_count} районів)"),
            ("● Червоний / Оранжевий БпЛА", f"Виявлені цілі (радар ЗСУ: {confirmed_count}, розвідка: {probable_count})"),
            ("── Вектор (+{horizon_minutes} хв)", f"Орієнтовний маршрут Shahed-136 (~180 км/год) з точкою прибуття"),
        ]
        if highlight_raion:
            leg_items.append(("■ Блакитний контур", f"Ваш район: {highlight_raion}"))

        fig.text(legend_x, legend_y + 0.14, "ЛЕГЕНДА ЗАГРОЗ (НЕЗАЛЕЖНІ РАЙОНИ):", color="#e2e8f0", fontsize=9, fontweight="bold")
        for i, (tag, desc) in enumerate(leg_items):
            y_pos = legend_y + 0.11 - (i * 0.024)
            fig.text(legend_x, y_pos, f"• {tag}: ", color="#cbd5e1", fontsize=8.0, fontweight="bold")
            fig.text(legend_x + 0.17, y_pos, desc, color="#94a3b8", fontsize=8.0)

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
