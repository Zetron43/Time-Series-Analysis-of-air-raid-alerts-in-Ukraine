"""Kinematic Threat & ETA Calculator for Air Raid Monitoring at Raion Level.

Calculates:
1. Distance between active aerial threats (drones, missiles) and raion centroids.
2. Forward bearing from threat to target raion.
3. Angle of deviation (approaching directly vs tangent vs flying away).
4. Estimated Time of Arrival (ETA) in minutes based on real-time kinematic velocity vectors.
"""

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

RAIONS_GEOJSON_PATH = Path(__file__).resolve().parents[2] / "data" / "ukraine_raions.geojson"

RAION_ALIASES = {
    "володимир-волинський": "володимирський",
    "новоград-волинський": "звягельський",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the great circle distance between two points on Earth in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def forward_bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the initial forward bearing from point 1 to point 2 in degrees (0-360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def heading_to_cardinal_ukr(deg: float) -> str:
    """Converts azimuth degrees to Ukrainian cardinal direction."""
    deg = deg % 360.0
    val = int((deg / 22.5) + 0.5)
    directions = [
        "Північ", "Пн-Пн-Сх", "Північний Схід", "Сх-Пн-Сх",
        "Схід", "Сх-Пд-Сх", "Південний Схід", "Пд-Пд-Сх",
        "Південь", "Пд-Пд-Зх", "Південний Захід", "Зх-Пд-Зх",
        "Захід", "Зх-Пн-Зх", "Північний Захід", "Пн-Пн-Зх",
    ]
    return directions[val % 16]


class KinematicETACalculator:
    """Computes exact distance, flight course, and ETA for raions across Ukraine."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, geojson_path: Optional[Path] = None):
        if self._initialized:
            return
        self.geojson_path = geojson_path or RAIONS_GEOJSON_PATH
        self.centroids: Dict[str, Tuple[float, float]] = {}
        self._load_centroids()
        self._initialized = True

    def _load_centroids(self):
        """Loads and computes centroid (lat, lon) for all 137 raions."""
        if not self.geojson_path.exists():
            return
        try:
            with open(self.geojson_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                r_name = props.get("rayon", "").strip()
                if not r_name:
                    continue
                clean_name = r_name.lower().replace(" район", "").strip()
                if clean_name in RAION_ALIASES:
                    clean_name = RAION_ALIASES[clean_name]

                geom = feat.get("geometry", {})
                coords = geom.get("coordinates", [])
                gtype = geom.get("type")
                all_pts = []
                if gtype == "Polygon":
                    for ring in coords:
                        all_pts.extend(ring)
                elif gtype == "MultiPolygon":
                    for poly in coords:
                        for ring in poly:
                            all_pts.extend(ring)

                if all_pts:
                    lons = [pt[0] for pt in all_pts]
                    lats = [pt[1] for pt in all_pts]
                    centroid = (sum(lats) / len(lats), sum(lons) / len(lons))
                    self.centroids[clean_name] = centroid
        except Exception as e:
            print(f"[KinematicETACalculator] Error loading centroids: {e}")

    def get_raion_centroid(self, raion_name: str) -> Optional[Tuple[float, float]]:
        """Resolves raion name to its center (lat, lon)."""
        clean = raion_name.lower().replace(" район", "").strip()
        if clean in RAION_ALIASES:
            clean = RAION_ALIASES[clean]
        if clean in self.centroids:
            return self.centroids[clean]
        for k, v in self.centroids.items():
            if clean in k or k in clean:
                return v
        return None

    def calculate_eta_for_raion(
        self,
        raion_name: str,
        threats: List[Dict[str, Any]],
        default_speed_kmh: float = 180.0,
    ) -> Dict[str, Any]:
        """Calculates tactical distance, approach angle, and ETA for a specific raion.

        Returns structured summary:
        {
            "raion": str,
            "centroid": (lat, lon),
            "threat_count": int,
            "has_direct_threat": bool,
            "min_eta_minutes": Optional[float],
            "min_distance_km": Optional[float],
            "summary_text": str,
            "details": List[Dict]
        }
        """
        centroid = self.get_raion_centroid(raion_name)
        if not centroid:
            return {
                "raion": raion_name,
                "centroid": None,
                "threat_count": 0,
                "has_direct_threat": False,
                "min_eta_minutes": None,
                "min_distance_km": None,
                "summary_text": "Координати центру району не визначено.",
                "details": [],
            }

        r_lat, r_lon = centroid
        direct_threats = []
        tangent_threats = []
        overhead_threats = []
        all_evaluated = []

        min_eta: Optional[float] = None
        min_dist: Optional[float] = None

        for t in threats:
            t_lat = t.get("lat")
            t_lon = t.get("lon")
            if t_lat is None or t_lon is None:
                continue

            heading = t.get("heading")
            speed = float(t.get("speed_kmh") or default_speed_kmh)
            count = int(t.get("count", 1) or 1)
            is_confirmed = t.get("is_confirmed", False) or t.get("lifecycle") == "confirmed"

            dist_km = haversine_km(t_lat, t_lon, r_lat, r_lon)
            bearing_to_raion = forward_bearing_degrees(t_lat, t_lon, r_lat, r_lon)

            if min_dist is None or dist_km < min_dist:
                min_dist = dist_km

            threat_item = {
                "source_pos": (t_lat, t_lon),
                "distance_km": round(dist_km, 1),
                "heading": heading,
                "bearing_to_raion": round(bearing_to_raion, 1),
                "count": count,
                "is_confirmed": is_confirmed,
                "eta_minutes": None,
                "status": "UNKNOWN",
            }

            # 1. Very close to the raion centroid (< 18 km)
            if dist_km <= 18.0:
                threat_item["status"] = "OVERHEAD"
                threat_item["eta_minutes"] = 0.0
                overhead_threats.append(threat_item)
                all_evaluated.append(threat_item)
                min_eta = 0.0
                continue

            # 2. Heading is available -> calculate directional approach angle
            if heading is not None:
                angle_diff = abs((heading - bearing_to_raion + 180.0) % 360.0 - 180.0)
                threat_item["angle_diff"] = round(angle_diff, 1)

                if angle_diff <= 45.0:
                    # Heading directly towards the raion
                    v_radial = speed * math.cos(math.radians(angle_diff))
                    if v_radial > 20.0:
                        eta_calc = (dist_km / v_radial) * 60.0
                        threat_item["eta_minutes"] = round(eta_calc, 0)
                        threat_item["status"] = "DIRECT_APPROACH"
                        direct_threats.append(threat_item)
                        if min_eta is None or eta_calc < min_eta:
                            min_eta = eta_calc
                elif angle_diff <= 85.0:
                    # Flying tangent / adjacent
                    cpa_dist = dist_km * math.sin(math.radians(angle_diff))
                    threat_item["cpa_dist_km"] = round(cpa_dist, 1)
                    if cpa_dist <= 30.0:
                        threat_item["status"] = "TANGENT_PASSING"
                        tangent_threats.append(threat_item)
                    else:
                        threat_item["status"] = "PASSING_BY"
                else:
                    threat_item["status"] = "RECEDING"
            else:
                # Heading unknown (e.g. static radar contact or acoustic observation)
                if dist_km <= 35.0:
                    threat_item["status"] = "PROXIMITY_ALERT"
                    direct_threats.append(threat_item)
                    rough_eta = (dist_km / speed) * 60.0
                    threat_item["eta_minutes"] = round(rough_eta, 0)
                    if min_eta is None or rough_eta < min_eta:
                        min_eta = rough_eta
                else:
                    threat_item["status"] = "DISTANT"

            all_evaluated.append(threat_item)

        # Formulate human-friendly Ukrainian summary
        if overhead_threats:
            summary = "🚨 ЦІЛЬ БЕЗПОСЕРЕДНЬО НАД РАЙОНОМ (або в зоні прямого підльоту <15 км)!"
        elif direct_threats:
            d_first = min(direct_threats, key=lambda x: x.get("eta_minutes") or 999)
            eta_val = int(d_first.get("eta_minutes", 15))
            dist_val = d_first["distance_km"]
            heading_str = heading_to_cardinal_ukr(d_first["heading"]) if d_first.get("heading") is not None else "курс уточнюється"
            summary = f"⏳ ПІДЛІТ У БІК РАЙОНУ: ~{max(5, eta_val - 2)}–{eta_val + 3} хв (дистанція {dist_val} км, напрямок: {heading_str})"
        elif tangent_threats:
            t_first = tangent_threats[0]
            summary = f"⚠️ Траєкторія проходить повз район (дистанція зближення ~{t_first.get('cpa_dist_km', 25)} км). Будьте уважні."
        elif min_dist is not None and min_dist <= 80.0:
            summary = f"ℹ️ Фіксуються цілі за {round(min_dist)} км, проте курс не спрямований у район."
        else:
            summary = "🟢 Прямих повітряних загроз на курсі до району наразі не виявлено."

        return {
            "raion": raion_name,
            "centroid": centroid,
            "threat_count": len(all_evaluated),
            "has_direct_threat": bool(overhead_threats or direct_threats),
            "min_eta_minutes": min_eta,
            "min_distance_km": round(min_dist, 1) if min_dist is not None else None,
            "summary_text": summary,
            "direct_threats_count": len(direct_threats) + len(overhead_threats),
            "details": sorted(all_evaluated, key=lambda x: x["distance_km"])[:5],
        }
