"""Web assets: building massing (local metres) and WebP cube faces.

Output layout (``data/out/``, published to the asset host, never to git)::

    buildings.json                 massing in local metres (x east, y north)
    panos/<scene>/<face>.webp      1300 px cube faces for the 360 viewer
    panos/<scene>/<face>_s.webp    384 px faces for instant previews
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from amap_pipeline.acquire.store import FACES
from amap_pipeline.geo.building_style import style_records
from amap_pipeline.geo.context import Context
from amap_pipeline.geo.osm import Building, Greenery, Ground

LEVEL_HEIGHT_M = 3.2
DEFAULT_LEVELS = 3
SMALL_FACE_PX = 384


@dataclass(frozen=True, slots=True)
class MassingParams:
    radius_m: float = 1200.0
    default_levels: int = DEFAULT_LEVELS


def building_height_m(
    building: Building, default_levels: int = DEFAULT_LEVELS
) -> float:
    levels = (
        building.levels if building.levels and building.levels > 0 else default_levels
    )
    return round(levels * LEVEL_HEIGHT_M, 2)


def massing(
    buildings: Iterable[Building],
    params: MassingParams = MassingParams(),  # noqa: B008
    context: Context | None = None,
    streets: BaseGeometry | None = None,
) -> dict[str, Any]:
    """Buildings within ``radius_m`` of the campus origin, ready to extrude.

    Each building carries a style, a height and a roof
    (:mod:`amap_pipeline.geo.building_style`); ``context`` (land use and POIs)
    sharpens the style of footprints tagged only ``building=yes``.
    """
    origin = Point(0.0, 0.0)
    kept = [b for b in buildings if b.outline.distance(origin) <= params.radius_m]
    features: list[dict[str, Any]] = []
    styled_all = style_records(kept, context, streets)
    for b, styled in zip(kept, styled_all, strict=True):
        ring = [[round(x, 2), round(y, 2)] for x, y in b.outline.exterior.coords]
        feature: dict[str, Any] = {
            "id": b.osm_id,
            "name": b.name,
            "campus": styled["style"] == "campus",
            **styled,
            "outline": ring,
        }
        # Campus registry facts (configs/campus.toml): the block code the map
        # chips show and, once surveyed, the facade recipe.
        for key in ("code", "facade"):
            if b.registry.get(key):
                feature[key] = b.registry[key]
        features.append(feature)
    return {
        "crs": "local-enu",
        "origin": "campus origin (amap_contracts.CAMPUS_ORIGIN_LAT/LNG)",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "buildings": features,
    }


def write_massing(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def export_panos(
    scenes: Sequence[str], tiles_dir: Path, out_dir: Path, quality: int = 82
) -> int:
    """Write full and small WebP faces per scene; returns the number of files."""
    written = 0
    for scene in scenes:
        target = out_dir / scene
        target.mkdir(parents=True, exist_ok=True)
        for face in FACES:
            with Image.open(tiles_dir / scene / f"{face}.jpg") as img:
                rgb = img.convert("RGB")
                rgb.save(target / f"{face}.webp", "WEBP", quality=quality, method=5)
                small = rgb.resize(
                    (SMALL_FACE_PX, SMALL_FACE_PX), Image.Resampling.LANCZOS
                )
                small.save(
                    target / f"{face}_s.webp", "WEBP", quality=quality - 6, method=5
                )
            written += 2
    return written


def greenery_json(greenery: Greenery, radius_m: float = 450.0) -> dict[str, Any]:
    """Parks/grass polygons and tree points near the campus, in local metres."""
    origin = Point(0.0, 0.0)
    areas = [
        {
            "kind": kind,
            "outline": [[round(x, 2), round(y, 2)] for x, y in outline.exterior.coords],
        }
        for kind, outline in greenery.areas
        if outline.distance(origin) <= radius_m
    ]
    trees = [
        [round(x, 2), round(y, 2)]
        for x, y in greenery.trees
        if Point(x, y).distance(origin) <= radius_m
    ]
    return {
        "crs": "local-enu",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "areas": areas,
        "trees": trees,
    }


GROUND_CLIP_MARGIN_M = 50.0


def _line_parts(geometry: object) -> list[LineString]:
    """Non-empty LineStrings in an intersection result."""
    if isinstance(geometry, LineString):
        return [] if geometry.is_empty else [geometry]
    if isinstance(geometry, MultiLineString) or hasattr(geometry, "geoms"):
        parts: list[LineString] = []
        for part in getattr(geometry, "geoms", []):
            parts.extend(_line_parts(part))
        return parts
    return []


def ground_json(ground: Ground, radius_m: float = 600.0) -> dict[str, Any]:
    """Streets/footpaths and ground areas near the campus, in local metres.

    Ways are clipped to a circle of ``radius_m + 50`` so long roads stay local;
    areas are kept whole. Campus areas come first so they are drawn underneath.
    """
    origin = Point(0.0, 0.0)
    clip = origin.buffer(radius_m + GROUND_CLIP_MARGIN_M)
    ways: list[dict[str, Any]] = []
    for way in ground.ways:
        for part in _line_parts(way.line.intersection(clip)):
            if part.distance(origin) > radius_m:
                continue
            ways.append(
                {
                    "kind": way.kind,
                    "name": way.name,
                    "width_m": way.width_m,
                    "line": [[round(x, 2), round(y, 2)] for x, y in part.coords],
                }
            )
    near = [a for a in ground.areas if a.outline.distance(origin) <= radius_m]
    near.sort(key=lambda a: a.kind != "campus")  # stable: campus first
    areas = [
        {
            "kind": a.kind,
            "name": a.name,
            "outline": [
                [round(x, 2), round(y, 2)] for x, y in a.outline.exterior.coords
            ],
        }
        for a in near
    ]
    return {
        "crs": "local-enu",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "ways": ways,
        "areas": areas,
    }
