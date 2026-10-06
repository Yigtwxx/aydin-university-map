"""Regional base map (land, near-shore sea, trunk roads, runways) in local metres.

Sources: Natural Earth 10m land (public domain) and OpenStreetMap (ODbL).
Everything is projected with :class:`LocalProjector`, so x/y share the origin of
the buildings, greenery and ground exports.
"""

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, polygonize, unary_union

from amap_contracts import BBox
from amap_pipeline.geo.osm import USER_AGENT, LocalProjector, _post_overpass

log = logging.getLogger(__name__)

NATURAL_EARTH_LAND_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_land.geojson"
)

LAND_BBOX = BBox(south=40.70, west=28.30, north=41.35, east=29.60)
SEA_BBOX = BBox(south=40.94, west=28.70, north=41.02, east=28.90)
ROADS_BBOX = BBox(south=40.90, west=28.60, north=41.10, east=29.00)

ROAD_KINDS = frozenset(
    {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}
)
MIN_ROAD_SEGMENT_M = 30.0
DEFAULT_RUNWAY_WIDTH_M = 45.0
MIN_POLYGON_AREA_M2 = 4.0

ATTRIBUTION = "© OpenStreetMap contributors (ODbL); Natural Earth (public domain)"


def _bbox_str(bbox: BBox) -> str:
    return f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"


def _cached_overpass(query: str, cache: Path) -> dict[str, Any]:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    payload = _post_overpass(urllib.parse.urlencode({"data": query}).encode())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def coastline_query(bbox: BBox) -> str:
    return (
        "[out:json][timeout:90];"
        f'way["natural"="coastline"]({_bbox_str(bbox)});'
        "out geom;"
    )


def roads_query(bbox: BBox) -> str:
    kinds = "|".join(sorted(ROAD_KINDS))
    return (
        "[out:json][timeout:90];"
        f'way["highway"~"^({kinds})$"]({_bbox_str(bbox)});'
        "out geom tags;"
    )


def aeroway_query(bbox: BBox) -> str:
    box_ = _bbox_str(bbox)
    return (
        "[out:json][timeout:90];("
        f'way["aeroway"="runway"]({box_});'
        f'way["aeroway"="aerodrome"]({box_});'
        f'relation["aeroway"="aerodrome"]({box_});'
        ");out geom;"
    )


def fetch_coastline_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for ``natural=coastline`` ways (cached on disk)."""
    return _cached_overpass(coastline_query(bbox), cache)


def fetch_roads_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for trunk-level highways (cached on disk)."""
    return _cached_overpass(roads_query(bbox), cache)


def fetch_aeroway_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for runways and aerodromes (cached on disk)."""
    return _cached_overpass(aeroway_query(bbox), cache)


def fetch_land_raw(cache: Path, url: str = NATURAL_EARTH_LAND_URL) -> dict[str, Any]:
    """Natural Earth 10m land GeoJSON (downloaded once, cached on disk)."""
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        raw: bytes = response.read()
    payload: dict[str, Any] = json.loads(raw)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    return payload


# --- geometry helpers ------------------------------------------------------------


def _polygons(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiPolygon) or hasattr(geometry, "geoms"):
        out: list[Polygon] = []
        for part in getattr(geometry, "geoms", []):
            out.extend(_polygons(part))
        return out
    return []


def _lines(geometry: BaseGeometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    out: list[LineString] = []
    for part in getattr(geometry, "geoms", []):
        out.extend(_lines(part))
    return out


def _project_polygon(polygon: Polygon, projector: LocalProjector) -> Polygon:
    def ring(coords: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
        return [projector.to_local(c[0], c[1]) for c in coords]

    return Polygon(
        ring(polygon.exterior.coords), [ring(h.coords) for h in polygon.interiors]
    )


def _round_ring(ring: Iterable[Sequence[float]]) -> list[list[float]]:
    return [[round(c[0], 1), round(c[1], 1)] for c in ring]


def polygon_records(polygons: Iterable[Polygon]) -> list[dict[str, Any]]:
    """``{"outer": ring, "holes": [ring, ...]}`` records, outer rings CCW."""
    records: list[dict[str, Any]] = []
    for polygon in polygons:
        poly = orient(polygon)
        records.append(
            {
                "outer": _round_ring(poly.exterior.coords),
                "holes": [_round_ring(h.coords) for h in poly.interiors],
            }
        )
    return records


def _simplified_polygons(geometry: BaseGeometry, tolerance_m: float) -> list[Polygon]:
    result: list[Polygon] = []
    for polygon in _polygons(geometry):
        simple = polygon.simplify(tolerance_m, preserve_topology=True)
        result.extend(p for p in _polygons(simple) if p.area >= MIN_POLYGON_AREA_M2)
    return result


# --- land ------------------------------------------------------------------------


def parse_land(
    payload: dict[str, Any],
    projector: LocalProjector,
    bbox: BBox = LAND_BBOX,
    tolerance_m: float = 120.0,
) -> list[Polygon]:
    """Land polygons clipped to ``bbox`` (lon/lat), projected and simplified."""
    clip = box(bbox.west, bbox.south, bbox.east, bbox.north)
    out: list[Polygon] = []
    for feature in payload.get("features", []):
        geometry = shape(feature["geometry"])
        if not geometry.intersects(clip):
            continue
        for part in _polygons(geometry.intersection(clip)):
            projected = _project_polygon(part, projector)
            out.extend(_simplified_polygons(projected, tolerance_m))
    return out


# --- near-shore sea ------------------------------------------------------------


def _way_line(element: dict[str, Any], projector: LocalProjector) -> LineString | None:
    coords = [
        projector.to_local(p["lon"], p["lat"]) for p in element.get("geometry", [])
    ]
    if len(coords) < 2:
        return None
    line = LineString(coords)
    return line if line.length > 0 else None


def parse_sea(
    payload: dict[str, Any],
    projector: LocalProjector,
    bbox: BBox = SEA_BBOX,
    tolerance_m: float = 4.0,
) -> list[Polygon]:
    """Sea polygon(s) inside ``bbox``: the bbox split by the OSM coastline.

    The piece holding the midpoint of the bbox's south edge is the sea (Florya
    faces the Marmara to the south). Returns ``[]`` (with a warning) if the
    coastline does not split the bbox.
    """
    corners = [
        projector.to_local(lng, lat)
        for lng, lat in (
            (bbox.west, bbox.south),
            (bbox.east, bbox.south),
            (bbox.east, bbox.north),
            (bbox.west, bbox.north),
        )
    ]
    frame = Polygon(corners)
    lines = [
        ln
        for el in payload.get("elements", [])
        if el.get("type") == "way"
        for ln in [_way_line(el, projector)]
        if ln is not None
    ]
    if not lines:
        log.warning("no coastline ways in payload; sea_near is empty")
        return []
    merged = linemerge(MultiLineString(lines))
    if not merged.intersects(frame):
        log.warning("coastline does not cross the bbox; sea_near is empty")
        return []
    # Lines run past the frame, so the union nodes them exactly on its edges;
    # polygonize drops the dangling parts outside.
    noded = unary_union([frame.exterior, merged])
    pieces = [p for p in polygonize(noded) if frame.contains(p.representative_point())]
    if len(pieces) < 2:
        log.warning(
            "coastline did not split the bbox (%d piece); sea_near empty", len(pieces)
        )
        return []
    south_mid = Point(
        (corners[0][0] + corners[1][0]) / 2, (corners[0][1] + corners[1][1]) / 2
    ).buffer(0.5)
    probe = Point(south_mid.centroid.x, south_mid.centroid.y + 0.5)
    sea = [p for p in pieces if p.contains(probe) or p.intersects(south_mid)]
    if not sea:
        log.warning("no piece contains the south edge midpoint; sea_near is empty")
        return []
    return _simplified_polygons(unary_union(sea), tolerance_m)


# --- roads -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegionRoad:
    kind: str
    name: str | None
    line: LineString  # local metres


def parse_roads(
    payload: dict[str, Any],
    projector: LocalProjector,
    tolerance_m: float = 8.0,
    min_length_m: float = MIN_ROAD_SEGMENT_M,
) -> list[RegionRoad]:
    """Trunk-level highways (links included), merged per kind and name.

    Touching ways of the same road are joined, then simplified; pieces shorter
    than ``min_length_m`` are dropped.
    """
    groups: dict[tuple[str, str | None], list[LineString]] = {}
    for element in payload.get("elements", []):
        tags: dict[str, str] = element.get("tags", {})
        kind = tags.get("highway", "")
        if element.get("type") != "way" or kind not in ROAD_KINDS:
            continue
        line = _way_line(element, projector)
        if line is not None:
            groups.setdefault((kind, tags.get("name")), []).append(line)
    roads: list[RegionRoad] = []
    for (kind, name), lines in groups.items():
        # Joining touching ways of one road keeps the record count small.
        for part in _lines(linemerge(MultiLineString(lines))):
            if part.length < min_length_m:
                continue
            simple = part.simplify(tolerance_m, preserve_topology=False)
            if isinstance(simple, LineString) and simple.length >= min_length_m:
                roads.append(RegionRoad(kind, name, simple))
    return roads


# --- aeroways --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Runway:
    width_m: float
    line: LineString


@dataclass(frozen=True, slots=True)
class Aerodrome:
    name: str | None
    outline: Polygon


def runway_width_m(tags: dict[str, str]) -> float:
    """OSM ``width`` tag in metres (tolerates "45 m" and "45,5"); default 45."""
    raw = tags.get("width", "").lower().replace("m", "").replace(",", ".").strip()
    try:
        width = float(raw)
    except ValueError:
        return DEFAULT_RUNWAY_WIDTH_M
    return width if width > 0 else DEFAULT_RUNWAY_WIDTH_M


def parse_aeroways(
    payload: dict[str, Any], projector: LocalProjector
) -> tuple[list[Runway], list[Aerodrome]]:
    """Runway centrelines and aerodrome outlines (outer rings) in local metres."""
    runways: list[Runway] = []
    aerodromes: list[Aerodrome] = []
    for element in payload.get("elements", []):
        tags: dict[str, str] = element.get("tags", {})
        aeroway = tags.get("aeroway")
        if aeroway == "runway" and element.get("type") == "way":
            line = _way_line(element, projector)
            if line is not None:
                runways.append(Runway(runway_width_m(tags), line))
        elif aeroway == "aerodrome":
            name = tags.get("name")
            if element.get("type") == "way":
                coords = [
                    projector.to_local(p["lon"], p["lat"])
                    for p in element.get("geometry", [])
                ]
                rings = [coords]
            else:
                rings = []
                outers = [
                    LineString(
                        [projector.to_local(p["lon"], p["lat"]) for p in m["geometry"]]
                    )
                    for m in element.get("members", [])
                    if m.get("role") == "outer" and len(m.get("geometry", [])) >= 2
                ]
                for poly in polygonize(unary_union(outers)) if outers else []:
                    rings.append(list(poly.exterior.coords))
            for ring in rings:
                if len(ring) < 4:
                    continue
                polygon = Polygon(ring)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                for part in _polygons(polygon):
                    if part.area >= MIN_POLYGON_AREA_M2:
                        aerodromes.append(Aerodrome(name, part))
    return runways, aerodromes
