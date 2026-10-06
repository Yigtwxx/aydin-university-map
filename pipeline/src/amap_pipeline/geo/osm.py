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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.validation import make_valid

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG, METRIC_CRS, BBox

FloatArray = NDArray[np.float64]

# The main instance first; kumi.systems as the fallback. (private.coffee and
# others were dropped after timing out for hours on 2026-10-06.)
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = (
    "aydin-university-map/0.1 (+https://github.com/Yigtwxx/aydin-university-map)"
)

# Campus plus a margin for the surrounding streets.
CAMPUS_OSM_BBOX = BBox(south=40.9860, west=28.7900, north=40.9950, east=28.8010)
# About 2.4 km square around the campus: the neighbourhood the map shows.
WIDE_OSM_BBOX = BBox(south=40.9805, west=28.7826, north=41.0025, east=28.8116)

# Tags the building styling reads (geo.building_style); the rest are dropped.
STYLE_TAGS = frozenset(
    {
        "building",
        "building:levels",
        "building:colour",
        "building:material",
        "roof:shape",
        "roof:colour",
        "roof:material",
        "roof:levels",
        "min_height",
        "height",
        "amenity",
        "shop",
        "office",
        "tourism",
        "leisure",
        "aeroway",
        "religion",
        "brand",
    }
)


@dataclass(frozen=True, slots=True)
class Building:
    osm_id: str
    name: str | None
    levels: float | None
    outline: Polygon  # local metres (x east, y north)
    tags: Mapping[str, str] = field(default_factory=dict, hash=False, compare=False)


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

    def to_local_arrays(
        self, lng: FloatArray, lat: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Vectorised :meth:`to_local`: arrays of lng/lat to arrays of x/y."""
        x, y = self._fwd.transform(np.asarray(lng, float), np.asarray(lat, float))
        return np.asarray(x) - self.origin[0], np.asarray(y) - self.origin[1]

    def to_wgs84_arrays(
        self, x: FloatArray, y: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Vectorised :meth:`to_wgs84`: arrays of x/y to arrays of (lng, lat)."""
        lng, lat = self._inv.transform(
            np.asarray(x, float) + self.origin[0], np.asarray(y, float) + self.origin[1]
        )
        return np.asarray(lng), np.asarray(lat)


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


def _post_overpass(
    body: bytes, attempts_per_mirror: int = 2, timeout_s: float = 90.0
) -> dict[str, Any]:
    """POST to Overpass, rotating mirrors with backoff on 429/5xx/timeouts."""
    errors: list[str] = []
    for url in OVERPASS_URLS:
        for attempt in range(attempts_per_mirror):
            request = urllib.request.Request(
                url, data=body, headers={"User-Agent": USER_AGENT}
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_s) as response:
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
                    tags={k: v for k, v in tags.items() if k in STYLE_TAGS},
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


def greenery_query(bbox: BBox) -> str:
    box = f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"
    return (
        "[out:json][timeout:60];("
        f'way["leisure"~"park|garden|pitch"]({box});'
        f'way["landuse"~"grass|recreation_ground|forest|meadow"]({box});'
        f'way["natural"~"wood|scrub|grassland"]({box});'
        f'node["natural"="tree"]({box});'
        ");out geom tags;"
    )


def fetch_greenery_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for parks, grass and single trees (cached on disk)."""
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": greenery_query(bbox)}).encode()
    payload = _post_overpass(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


@dataclass(frozen=True, slots=True)
class Greenery:
    areas: list[tuple[str, Polygon]]  # (kind, outline in local metres)
    trees: list[tuple[float, float]]  # local metres


def parse_greenery(payload: dict[str, Any], projector: LocalProjector) -> Greenery:
    areas: list[tuple[str, Polygon]] = []
    trees: list[tuple[float, float]] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        if element.get("type") == "node":
            trees.append(projector.to_local(element["lon"], element["lat"]))
            continue
        kind = (
            tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "grass"
        )
        coords = [
            projector.to_local(p["lon"], p["lat"]) for p in element.get("geometry", [])
        ]
        if len(coords) >= 4:
            outline = Polygon(coords)
            if outline.is_valid and outline.area >= 4.0:
                areas.append((kind, outline))
    return Greenery(areas, trees)


# --- ground layer: streets, footpaths and ground areas ---------------------------

# Highway values that are not walkable/drivable ground lines (or are indoor).
_SKIPPED_HIGHWAYS = frozenset(
    {
        "proposed",
        "construction",
        "abandoned",
        "platform",
        "bus_stop",
        "elevator",
        "corridor",
    }
)
_DEFAULT_WIDTH_M = 4.0
_WIDTH_BY_KIND: dict[str, float] = {
    "motorway": 14.0,
    "trunk": 14.0,
    "motorway_link": 7.0,
    "trunk_link": 7.0,
    "primary_link": 7.0,
    "busway": 7.0,
    "primary": 11.0,
    "secondary": 9.0,
    "tertiary": 8.0,
    "residential": 6.5,
    "unclassified": 6.5,
    "living_street": 6.5,
    "service": 4.5,
    "pedestrian": 5.0,
    "track": 3.0,
    "footway": 2.2,
    "path": 2.2,
    "cycleway": 2.2,
    "bridleway": 2.2,
    "steps": 2.0,
}
_MIN_AREA_M2 = 4.0


def ground_query(bbox: BBox) -> str:
    box = f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"
    return (
        "[out:json][timeout:60];("
        f'way["highway"]({box});'
        f'way["amenity"~"university|college|parking"]({box});'
        f'relation["amenity"~"university|college"]({box});'
        f'way["landuse"~"education"]({box});'
        f'way["highway"="pedestrian"]["area"="yes"]({box});'
        f'way["place"="square"]({box});'
        f'way["leisure"~"pitch|track|sports_centre"]({box});'
        f'way["natural"="water"]({box});'
        ");out geom;"  # tags + members; "tags" would drop relation members
    )


def fetch_ground_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for streets, footpaths and ground areas (cached on disk)."""
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": ground_query(bbox)}).encode()
    payload = _post_overpass(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


@dataclass(frozen=True, slots=True)
class GroundWay:
    kind: str  # OSM highway value
    name: str | None
    width_m: float
    line: LineString  # local metres


@dataclass(frozen=True, slots=True)
class GroundArea:
    kind: str  # campus | pedestrian | parking | pitch | water
    name: str | None
    outline: Polygon  # local metres


@dataclass(frozen=True, slots=True)
class Ground:
    ways: list[GroundWay]
    areas: list[GroundArea]


def _way_width_m(kind: str, tags: dict[str, str]) -> float:
    raw = tags.get("width", "").lower().replace("m", "").replace(",", ".").strip()
    try:
        width = float(raw)
    except ValueError:
        return _WIDTH_BY_KIND.get(kind, _DEFAULT_WIDTH_M)
    return width if width > 0 else _WIDTH_BY_KIND.get(kind, _DEFAULT_WIDTH_M)


def _area_kind(tags: dict[str, str]) -> str | None:
    amenity = tags.get("amenity", "")
    if amenity in ("university", "college") or tags.get("landuse") == "education":
        return "campus"
    if tags.get("place") == "square":
        return "pedestrian"
    if amenity == "parking":
        return "parking"
    if tags.get("leisure") in ("pitch", "track", "sports_centre"):
        return "pitch"
    if tags.get("natural") == "water":
        return "water"
    return None


def _valid_polygon(coords: Sequence[tuple[float, float]]) -> Polygon | None:
    """Polygon from a ring, repaired if needed; None if unusable or < 4 m2."""
    if len(coords) < 4:
        return None
    outline = Polygon(coords)
    if not outline.is_valid:
        fixed = make_valid(outline)
        if not isinstance(fixed, Polygon | MultiPolygon):
            fixed = outline.buffer(0)
        if isinstance(fixed, MultiPolygon):
            fixed = max(fixed.geoms, key=lambda g: g.area, default=None)
        if not isinstance(fixed, Polygon):
            return None
        outline = fixed
    if outline.is_empty or not outline.is_valid or outline.area < _MIN_AREA_M2:
        return None
    return outline


def parse_ground(payload: dict[str, Any], projector: LocalProjector) -> Ground:
    """Highway lines and ground-area polygons in local metres.

    Relations contribute only their closed outer member rings.
    """
    ways: list[GroundWay] = []
    areas: list[GroundArea] = []
    for element in payload.get("elements", []):
        tags: dict[str, str] = element.get("tags", {})
        name = tags.get("name")
        if element.get("type") == "relation":
            kind = _area_kind(tags)
            if kind is None:
                continue
            for member in element.get("members", []):
                if member.get("role") != "outer" or "geometry" not in member:
                    continue
                ring = [
                    projector.to_local(p["lon"], p["lat"]) for p in member["geometry"]
                ]
                if len(ring) < 4 or ring[0] != ring[-1]:
                    continue
                polygon = _valid_polygon(ring)
                if polygon is not None:
                    areas.append(GroundArea(kind, name, polygon))
            continue
        if element.get("type") != "way" or "geometry" not in element:
            continue
        coords = [projector.to_local(p["lon"], p["lat"]) for p in element["geometry"]]
        highway = tags.get("highway")
        if highway is not None:
            if highway in _SKIPPED_HIGHWAYS:
                continue
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            if highway == "pedestrian" and tags.get("area") == "yes" and closed:
                polygon = _valid_polygon(coords)
                if polygon is not None:
                    areas.append(GroundArea("pedestrian", name, polygon))
            elif len(coords) >= 2:
                line = LineString(coords)
                if line.length > 0:
                    ways.append(
                        GroundWay(highway, name, _way_width_m(highway, tags), line)
                    )
            continue
        kind = _area_kind(tags)
        if kind is None:
            continue
        polygon = _valid_polygon(coords)
        if polygon is not None:
            areas.append(GroundArea(kind, name, polygon))
    return Ground(ways, areas)
