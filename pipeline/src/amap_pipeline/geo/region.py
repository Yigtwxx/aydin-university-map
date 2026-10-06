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
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import shapely
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
from shapely.validation import make_valid

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


def _cached_overpass(
    query: str, cache: Path, timeout_s: float = 90.0
) -> dict[str, Any]:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    payload = _post_overpass(
        urllib.parse.urlencode({"data": query}).encode(),
        timeout_s=timeout_s + 30.0,  # client waits a bit longer than the server
    )
    remark = str(payload.get("remark", ""))
    if "error" in remark.lower():
        # A server-side timeout still answers 200 with partial data: never cache it.
        raise RuntimeError(f"Overpass query failed: {remark}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(cache.suffix + ".part")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(cache)  # atomic: an interrupted run never leaves a torn cache
    return payload


def coastline_query(bbox: BBox, timeout_s: int = 90) -> str:
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["natural"="coastline"]({_bbox_str(bbox)});'
        "out geom;"
    )


def roads_query(
    bbox: BBox, kinds: Iterable[str] = ROAD_KINDS, timeout_s: int = 90
) -> str:
    pattern = "|".join(sorted(kinds))
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({pattern})$"]({_bbox_str(bbox)});'
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


def fetch_coastline_raw(bbox: BBox, cache: Path, timeout_s: int = 90) -> dict[str, Any]:
    """Overpass JSON for ``natural=coastline`` ways (cached on disk)."""
    return _cached_overpass(coastline_query(bbox, timeout_s), cache, timeout_s)


def fetch_roads_raw(
    bbox: BBox,
    cache: Path,
    kinds: Iterable[str] = ROAD_KINDS,
    timeout_s: int = 90,
) -> dict[str, Any]:
    """Overpass JSON for highways of ``kinds`` (trunk level by default; cached)."""
    return _cached_overpass(roads_query(bbox, kinds, timeout_s), cache, timeout_s)


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


# --- land/sea split of a large frame (coastline orientation) ---------------------


def coastline_lines(
    payload: dict[str, Any], projector: LocalProjector
) -> list[LineString]:
    """``natural=coastline`` ways as local-metre lines (one vectorised projection).

    OSM coastlines keep their way direction (land on the left), which
    :func:`coastline_faces` relies on.
    """
    ways = [
        el["geometry"]
        for el in payload.get("elements", [])
        if el.get("type") == "way" and len(el.get("geometry", [])) >= 2
    ]
    if not ways:
        return []
    lng = np.array([p["lon"] for way in ways for p in way], dtype=np.float64)
    lat = np.array([p["lat"] for way in ways for p in way], dtype=np.float64)
    x, y = projector.to_local_arrays(lng, lat)
    xy = np.column_stack([x, y])
    bounds = np.cumsum([0] + [len(way) for way in ways])
    lines = [LineString(xy[a:b]) for a, b in pairwise(bounds.tolist())]
    return [line for line in lines if line.length > 0]


@dataclass(frozen=True, slots=True)
class CoastFace:
    """One piece of a frame cut by the coastline.

    ``vote`` is the length (m) of coastline along the boundary that has the
    face on its left minus the length that has it on its right: > 0 is land,
    < 0 is water, 0 means no coastline touches the face.
    """

    polygon: Polygon
    vote: float


def _segments(lines: Sequence[LineString]) -> tuple[np.ndarray, np.ndarray]:
    """Start points and direction vectors of every coastline segment."""
    starts: list[np.ndarray] = []
    vectors: list[np.ndarray] = []
    for line in lines:
        coords = np.asarray(line.coords, dtype=np.float64)[:, :2]
        starts.append(coords[:-1])
        vectors.append(np.diff(coords, axis=0))
    return np.vstack(starts), np.vstack(vectors)


def coastline_faces(
    lines: Sequence[LineString], frame: Polygon, tolerance_m: float = 0.05
) -> list[CoastFace]:
    """Cut ``frame`` with the coastline and vote each face land or water.

    Every face is oriented counter-clockwise (interior on the left of each
    ring). A ring edge that lies on a coastline segment running the same way
    has land on the face side, so it votes land by its length; the opposite
    direction votes water. Frame edges touch no coastline and do not vote.
    Robust to a few reversed ways, which a single probe point is not.
    """
    crossing = [line for line in lines if line.intersects(frame)]
    if not crossing:
        return [CoastFace(frame, 0.0)]
    # Lines run past the frame, so the union nodes them exactly on its edges;
    # polygonize drops the dangling parts outside.
    noded = unary_union([frame.exterior, *crossing])
    faces = [
        orient(p, 1.0)
        for p in polygonize(noded)
        if frame.contains(p.representative_point())
    ]
    starts, vectors = _segments(crossing)
    segments = np.asarray(shapely.linestrings(np.stack([starts, starts + vectors], 1)))
    tree = shapely.STRtree(segments)
    mids: list[np.ndarray] = []
    edges: list[np.ndarray] = []
    owner: list[np.ndarray] = []
    for index, face in enumerate(faces):
        for ring in (face.exterior, *face.interiors):
            coords = np.asarray(ring.coords, dtype=np.float64)[:, :2]
            mids.append((coords[:-1] + coords[1:]) / 2)
            edges.append(np.diff(coords, axis=0))
            owner.append(np.full(len(coords) - 1, index))
    mid = np.vstack(mids)
    edge = np.vstack(edges)
    face_of = np.concatenate(owner)
    hit_edge, hit_seg = tree.query_nearest(
        shapely.points(mid), max_distance=tolerance_m, all_matches=False
    )
    agree = np.einsum("ij,ij->i", edge[hit_edge], vectors[hit_seg])
    length = np.hypot(edge[hit_edge, 0], edge[hit_edge, 1])
    votes = np.bincount(
        face_of[hit_edge], weights=np.sign(agree) * length, minlength=len(faces)
    )
    return [CoastFace(f, float(v)) for f, v in zip(faces, votes, strict=True)]


def classify_faces(
    faces: Sequence[CoastFace], fallback_land: BaseGeometry | None = None
) -> tuple[list[Polygon], list[Polygon]]:
    """``(land, water)`` from voted faces.

    Faces the coastline does not touch (vote 0) are land when at least half of
    them lies in ``fallback_land`` (e.g. Natural Earth); with no fallback they
    count as land.
    """
    land: list[Polygon] = []
    water: list[Polygon] = []
    undecided = 0
    for face in faces:
        is_land = face.vote > 0
        if face.vote == 0:
            undecided += 1
            if fallback_land is None:
                is_land = True
            else:
                overlap = face.polygon.intersection(fallback_land).area
                is_land = overlap >= 0.5 * face.polygon.area
        (land if is_land else water).append(face.polygon)
    if undecided:
        log.warning(
            "%d face(s) not touched by the coastline; classified by %s",
            undecided,
            "the fallback land" if fallback_land is not None else "default (land)",
        )
    return land, water


def split_land_sea(
    lines: Sequence[LineString],
    frame: Polygon,
    fallback_land: BaseGeometry | None = None,
) -> tuple[list[Polygon], list[Polygon]]:
    """``(land, water)`` polygons covering ``frame``, cut by the coastline."""
    return classify_faces(coastline_faces(lines, frame), fallback_land)


# --- inland water bodies -------------------------------------------------------------

# ``water=*`` values too small or artificial to matter at regional scale.
MINOR_WATER_KINDS = (
    "pond",
    "basin",
    "wastewater",
    "reflecting_pool",
    "fountain",
    "pool",
    "fishpond",
    "moat",
    "ditch",
    "drain",
)


def water_bodies_query(
    bbox: BBox, skip_kinds: Sequence[str] = (), timeout_s: int = 180
) -> str:
    """``natural=water`` (and legacy ``landuse=reservoir``) ways and relations."""
    box_ = _bbox_str(bbox)
    skip = f'["water"!~"^({"|".join(skip_kinds)})$"]' if skip_kinds else ""
    return (
        f"[out:json][timeout:{timeout_s}];("
        f'way["natural"="water"]{skip}({box_});'
        f'relation["natural"="water"]{skip}({box_});'
        f'way["landuse"="reservoir"]({box_});'
        f'relation["landuse"="reservoir"]({box_});'
        ");out geom;"
    )


def fetch_water_bodies_raw(
    bbox: BBox, cache: Path, skip_kinds: Sequence[str] = (), timeout_s: int = 180
) -> dict[str, Any]:
    """Overpass JSON for lakes, reservoirs and other water areas (cached on disk)."""
    return _cached_overpass(
        water_bodies_query(bbox, skip_kinds, timeout_s), cache, timeout_s
    )


def _project_points(
    points: Sequence[dict[str, float]], projector: LocalProjector
) -> np.ndarray:
    lng = np.array([p["lon"] for p in points], dtype=np.float64)
    lat = np.array([p["lat"] for p in points], dtype=np.float64)
    x, y = projector.to_local_arrays(lng, lat)
    return np.column_stack([x, y])


def _valid_parts(geometry: BaseGeometry) -> list[Polygon]:
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    return [p for p in _polygons(geometry) if p.area >= MIN_POLYGON_AREA_M2]


def _relation_water(
    element: dict[str, Any], projector: LocalProjector
) -> list[Polygon]:
    """Multipolygon relation: polygonized outer rings minus inner rings."""
    rings: dict[str, list[LineString]] = {"outer": [], "inner": []}
    for member in element.get("members", []):
        geometry = [p for p in member.get("geometry", []) if p]
        if member.get("type") != "way" or len(geometry) < 2:
            continue
        role = "inner" if member.get("role") == "inner" else "outer"
        rings[role].append(LineString(_project_points(geometry, projector)))
    if not rings["outer"]:
        return []
    shell = unary_union(list(polygonize(unary_union(rings["outer"]))))
    if rings["inner"]:
        shell = shell.difference(
            unary_union(list(polygonize(unary_union(rings["inner"]))))
        )
    return _valid_parts(shell)


def parse_water_bodies(
    payload: dict[str, Any], projector: LocalProjector
) -> list[Polygon]:
    """Closed water ways and multipolygon relations as local-metre polygons."""
    out: list[Polygon] = []
    for element in payload.get("elements", []):
        if element.get("type") == "relation":
            out.extend(_relation_water(element, projector))
            continue
        geometry = element.get("geometry", [])
        if element.get("type") != "way" or len(geometry) < 4:
            continue
        if geometry[0] != geometry[-1]:
            continue  # an unclosed way is only a piece of a relation
        out.extend(_valid_parts(Polygon(_project_points(geometry, projector))))
    return out
