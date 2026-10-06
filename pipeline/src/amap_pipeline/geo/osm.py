"""OpenStreetMap building footprints for the campus (OSM contributors, ODbL).

Footprints are fetched once from Overpass, cached under ``data/osm/`` and
projected to local metres: UTM 35N (EPSG:32635) minus the campus ENU origin, so
x = east and y = north.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer
from shapely.geometry import Polygon

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG, METRIC_CRS, BBox

FloatArray = NDArray[np.float64]

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = (
    "aydin-university-map/0.1 (+https://github.com/Yigtwxx/aydin-university-map)"
)

# Campus plus a margin for the surrounding streets.
CAMPUS_OSM_BBOX = BBox(south=40.9860, west=28.7900, north=40.9950, east=28.8010)


@dataclass(frozen=True, slots=True)
class Building:
    osm_id: str
    name: str | None
    levels: float | None
    outline: Polygon  # local metres (x east, y north)


class LocalProjector:
    """WGS84 <-> local metres around the campus origin."""

    def __init__(self) -> None:
        self._fwd = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
        self._inv = Transformer.from_crs(METRIC_CRS, "EPSG:4326", always_xy=True)
        ox, oy = self._fwd.transform(CAMPUS_ORIGIN_LNG, CAMPUS_ORIGIN_LAT)
        self.origin = (float(ox), float(oy))

    def to_local(self, lng: float, lat: float) -> tuple[float, float]:
        x, y = self._fwd.transform(lng, lat)
        return float(x) - self.origin[0], float(y) - self.origin[1]

    def to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        """Return (lng, lat)."""
        lng, lat = self._inv.transform(x + self.origin[0], y + self.origin[1])
        return float(lng), float(lat)


def overpass_query(bbox: BBox) -> str:
    box = f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"
    return (
        "[out:json][timeout:60];"
        f'(way["building"]({box});relation["building"]({box}););'
        "out geom tags;"
    )


def fetch_buildings_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for buildings in ``bbox`` (cached on disk)."""
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": overpass_query(bbox)}).encode()
    payload = _post_overpass(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _post_overpass(body: bytes, attempts_per_mirror: int = 2) -> dict[str, Any]:
    """POST to Overpass, rotating mirrors with backoff on 429/5xx/timeouts."""
    errors: list[str] = []
    for url in OVERPASS_URLS:
        for attempt in range(attempts_per_mirror):
            request = urllib.request.Request(
                url, data=body, headers={"User-Agent": USER_AGENT}
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return json.loads(response.read())
            except (urllib.error.URLError, TimeoutError) as exc:
                errors.append(f"{url} attempt {attempt + 1}: {exc}")
                time.sleep(5 * (attempt + 1))
    raise RuntimeError("Overpass unavailable: " + "; ".join(errors))


def _levels(tags: dict[str, str]) -> float | None:
    try:
        return float(tags["building:levels"])
    except (KeyError, ValueError):
        return None


def parse_buildings(
    payload: dict[str, Any], projector: LocalProjector
) -> list[Building]:
    """Ways and outer rings of multipolygon relations, as local-metre polygons."""
    buildings: list[Building] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        rings: list[Sequence[dict[str, float]]] = []
        if element.get("type") == "way" and "geometry" in element:
            rings.append(element["geometry"])
        elif element.get("type") == "relation":
            rings.extend(
                m["geometry"]
                for m in element.get("members", [])
                if m.get("role") == "outer" and "geometry" in m
            )
        for ring in rings:
            coords = [projector.to_local(p["lon"], p["lat"]) for p in ring]
            if len(coords) < 4:
                continue
            outline = Polygon(coords)
            if not outline.is_valid or outline.area < 4.0:
                continue
            buildings.append(
                Building(
                    osm_id=f"{element['type']}/{element['id']}",
                    name=tags.get("name"),
                    levels=_levels(tags),
                    outline=outline,
                )
            )
    return buildings


def sample_outlines(buildings: Sequence[Building], step_m: float = 0.5) -> FloatArray:
    """Points every ``step_m`` metres along all building outlines, shape (N, 2)."""
    samples: list[FloatArray] = []
    for building in buildings:
        ring = building.outline.exterior
        count = max(int(ring.length / step_m), 4)
        distances = np.linspace(0.0, ring.length, count, endpoint=False)
        points = [ring.interpolate(float(d)) for d in distances]
        samples.append(np.array([[p.x, p.y] for p in points]))
    return np.vstack(samples) if samples else np.zeros((0, 2))
