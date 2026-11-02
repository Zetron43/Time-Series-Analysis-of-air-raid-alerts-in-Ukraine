import json
from pathlib import Path
from typing import List, Tuple
from matplotlib.path import Path as MplPath

_GEOJSON_PATH = Path(__file__).resolve().parents[2] / "data" / "ukraine_raions.geojson"
_INDEXED_PATHS: List[Tuple[Tuple[float, float, float, float], MplPath]] = []
_INITIALIZED = False


def _init_border_paths():
    global _INDEXED_PATHS, _INITIALIZED
    if _INITIALIZED:
        return
    if not _GEOJSON_PATH.exists():
        _INITIALIZED = True
        return
    try:
        with open(_GEOJSON_PATH, "r", encoding="utf-8") as f:
            gj = json.load(f)
        for feat in gj.get("features", []):
            geom = feat.get("geometry", {})
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            polys = [coords] if gtype == "Polygon" else (coords if gtype == "MultiPolygon" else [])
            for poly in polys:
                if len(poly) > 0 and len(poly[0]) >= 3:
                    pts = poly[0]
                    lons = [p[0] for p in pts]
                    lats = [p[1] for p in pts]
                    bbox = (min(lons) - 0.08, max(lons) + 0.08, min(lats) - 0.08, max(lats) + 0.08)
                    _INDEXED_PATHS.append((bbox, MplPath(pts)))
    except Exception as e:
        print(f"[BorderFilter] Init error: {e}")
    finally:
        _INITIALIZED = True


def is_point_in_ukraine(lat: float, lon: float, margin_deg: float = 0.06) -> bool:
    """Checks whether (lat, lon) is within Ukrainian sovereign land or immediate coastal border."""
    if not _INITIALIZED:
        _init_border_paths()
    if not _INDEXED_PATHS:
        # Fallback to strict Ukraine bounding box if GeoJSON failed to load
        return 44.38 <= lat <= 52.38 and 22.14 <= lon <= 40.22

    # Fast reject if outside Ukraine outer bounds
    if lat < 44.35 or lat > 52.40 or lon < 22.10 or lon > 40.25:
        return False

    for (x0, x1, y0, y1), path in _INDEXED_PATHS:
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            if path.contains_point((lon, lat)):
                return True
    return False
