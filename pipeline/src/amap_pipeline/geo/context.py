"""Land use and points of interest around buildings (OSM contributors, ODbL).

Most OSM footprints in the neighbourhood are tagged only ``building=yes``.
What a building is mostly follows from where it stands (an industrial estate,
the airport apron, a school ground) and from the shops and offices mapped as
points inside it; :mod:`amap_pipeline.geo.building_style` reads both.
"""

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely import STRtree
from shapely.geometry import Point, Polygon

from amap_contracts import BBox
from amap_pipeline.geo.osm import LocalProjector, _post_overpass

AREA_KEYS = ("landuse", "aeroway", "amenity", "leisure")
POI_KEYS = ("shop", "amenity", "office", "tourism", "craft", "man_made")


def context_query(bbox: BBox) -> str:
    box = f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"
    areas = "".join(
        f'way["{k}"]({box});relation["{k}"]["type"="multipolygon"]({box});'
        for k in AREA_KEYS
    )
    pois = "".join(f'node["{k}"]({box});' for k in POI_KEYS)
    return f"[out:json][timeout:90];({areas}{pois});out geom tags;"


def fetch_context_raw(bbox: BBox, cache: Path) -> dict[str, Any]:
    """Overpass JSON for land use areas and POI nodes (cached on disk)."""
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": context_query(bbox)}).encode()
    payload = _post_overpass(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


@dataclass(frozen=True, slots=True)
class Area:
    kind: str  # "<key>:<value>", e.g. "landuse:industrial"
    outline: Polygon


@dataclass(frozen=True, slots=True)
class Poi:
    kind: str  # "<key>:<value>", e.g. "shop:car"
    point: Point


class Context:
    """Areas and POIs with spatial indexes for point-in-polygon lookups."""

    def __init__(self, areas: list[Area], pois: list[Poi]) -> None:
        self.areas = areas
        self.pois = pois
        self._area_tree = STRtree([a.outline for a in areas])
        self._poi_tree = STRtree([p.point for p in pois])

    def areas_at(self, point: Point) -> list[Area]:
        """Areas containing ``point``, smallest first (the most specific)."""
        hits = [
            self.areas[int(i)] for i in self._area_tree.query(point, predicate="within")
        ]
        return sorted(hits, key=lambda a: a.outline.area)

    def pois_in(self, outline: Polygon) -> list[Poi]:
        return [
            self.pois[int(i)]
            for i in self._poi_tree.query(outline, predicate="contains")
        ]


def _kind(tags: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in tags:
            return f"{key}:{tags[key]}"
    return None


def _ring(points: list[dict[str, float]], projector: LocalProjector) -> Polygon | None:
    coords = [projector.to_local(p["lon"], p["lat"]) for p in points]
    if len(coords) < 4 or coords[0] != coords[-1]:
        return None
    polygon = Polygon(coords)
    return polygon if polygon.is_valid and polygon.area > 1.0 else None


def parse_context(payload: dict[str, Any], projector: LocalProjector) -> Context:
    areas: list[Area] = []
    pois: list[Poi] = []
    for element in payload.get("elements", []):
        tags: dict[str, str] = element.get("tags", {})
        kind_type = element.get("type")
        if kind_type == "node":
            kind = _kind(tags, POI_KEYS)
            if kind:
                x, y = projector.to_local(element["lon"], element["lat"])
                pois.append(Poi(kind, Point(x, y)))
            continue
        kind = _kind(tags, AREA_KEYS)
        if kind is None:
            continue
        rings: list[list[dict[str, float]]] = []
        if kind_type == "way" and "geometry" in element:
            rings.append(element["geometry"])
        elif kind_type == "relation":
            rings.extend(
                m["geometry"]
                for m in element.get("members", [])
                if m.get("role") == "outer" and "geometry" in m
            )
        for ring in rings:
            polygon = _ring(ring, projector)
            if polygon is not None:
                areas.append(Area(kind, polygon))
    return Context(areas, pois)
