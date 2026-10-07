"""Hand corrections to the OSM footprints and the SfM poses.

``configs/building_overrides.toml``: OSM lacks some campus buildings and leaves
others unnamed; the 360 tour, the satellite view and the university's campus
map show what they are. Every command that reads footprints applies these, so
the map, the walking graph and the georeferencing see the same buildings.

``configs/pose_overrides.toml``: panoramas the SfM model put in the wrong
place, set where their own pictures (street, corners, signs) show they stand.

``data/derived/survey.json``: poses adjusted by ``amap survey solve`` from
bearings measured in the pictures. They are applied before the hand
overrides, which should shrink to nothing as the survey covers their scenes.
"""

import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon

from amap_pipeline.geo.campus import Registry, apply_campus, load_campus
from amap_pipeline.geo.osm import Building, LocalProjector

DEFAULT_BUILDING_OVERRIDES = (
    Path(__file__).parents[3] / "configs" / "building_overrides.toml"
)
DEFAULT_POSE_OVERRIDES = Path(__file__).parents[3] / "configs" / "pose_overrides.toml"


@dataclass(frozen=True, slots=True)
class BuildingOverrides:
    names: dict[str, str]  # OSM id -> name
    added: list[Building]


def load_building_overrides(
    path: Path | None = DEFAULT_BUILDING_OVERRIDES,
) -> BuildingOverrides:
    """Read ``[names]`` and ``[[add]]`` (outline in local metres, east/north;
    optional ``levels`` and OSM-style ``tags``)."""
    if path is None or not path.exists():
        return BuildingOverrides(names={}, added=[])
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    names = {str(k): str(v) for k, v in data.get("names", {}).items()}
    added: list[Building] = []
    for entry in data.get("add", []):
        osm_id = str(entry["id"])
        try:
            outline = Polygon([(float(x), float(y)) for x, y in entry["outline"]])
        except ValueError as exc:
            raise ValueError(f"{osm_id}: invalid outline in {path}") from exc
        if not outline.is_valid or outline.area < 4.0:
            raise ValueError(f"{osm_id}: invalid outline in {path}")
        levels = entry.get("levels")
        added.append(
            Building(
                osm_id=osm_id,
                name=str(entry["name"]),
                levels=float(levels) if levels is not None else None,
                outline=outline,
                tags={str(k): str(v) for k, v in entry.get("tags", {}).items()},
            )
        )
    return BuildingOverrides(names=names, added=added)


def apply_building_overrides(
    buildings: Sequence[Building],
    overrides: BuildingOverrides | None = None,
    campus: Registry | None = None,
) -> list[Building]:
    """Rename the listed footprints and append the missing ones, then apply the
    campus block registry (loaded from configs when neither is given)."""
    if overrides is None and campus is None:
        campus = load_campus()
    if overrides is None:
        overrides = load_building_overrides()
    renamed = [
        replace(b, name=overrides.names[b.osm_id]) if b.osm_id in overrides.names else b
        for b in buildings
    ]
    merged = [*renamed, *overrides.added]
    return apply_campus(merged, campus) if campus is not None else merged


@dataclass(frozen=True, slots=True)
class PoseOverride:
    x: float  # local metres east
    y: float  # local metres north
    heading_deg: float  # compass bearing of the panorama's front face


def load_pose_overrides(
    path: Path | None = DEFAULT_POSE_OVERRIDES,
) -> dict[str, PoseOverride]:
    """Read ``[poses.<scene>]`` tables with ``x``, ``y`` and ``heading_deg``."""
    if path is None or not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        str(scene): PoseOverride(
            x=float(entry["x"]),
            y=float(entry["y"]),
            heading_deg=float(entry["heading_deg"]) % 360.0,
        )
        for scene, entry in data.get("poses", {}).items()
    }


def apply_pose_overrides(
    posed: Mapping[str, Mapping[str, Any]],
    overrides: Mapping[str, PoseOverride],
    projector: LocalProjector,
) -> dict[str, dict[str, Any]]:
    """Move the listed scenes; the measured camera height stays."""
    result = {scene: dict(record) for scene, record in posed.items()}
    for scene, pose in overrides.items():
        if scene not in result:
            raise ValueError(f"{scene}: pose override for a scene no model placed")
        lng, lat = projector.to_wgs84(pose.x, pose.y)
        result[scene].update(
            x=pose.x,
            y=pose.y,
            lat=lat,
            lng=lng,
            heading_deg=pose.heading_deg,
            pose_source="manual",
        )
    return result


@dataclass(frozen=True, slots=True)
class SurveyPose:
    x: float
    y: float
    z: float  # camera height, only used for panoramas no model placed
    heading_deg: float
    surveyed: bool  # seen landmarks or solved freely (else: its model moved it)


def load_survey_poses(path: Path) -> dict[str, SurveyPose]:
    """Poses from ``amap survey solve`` (``data/derived/survey.json``)."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(scene): SurveyPose(
            x=float(p["x"]),
            y=float(p["y"]),
            z=float(p["z"]),
            heading_deg=float(p["heading_deg"]) % 360.0,
            surveyed=bool(p["free"]) or int(p.get("sightings", 0)) > 0,
        )
        for scene, p in data["poses"].items()
    }


def apply_survey_poses(
    posed: Mapping[str, Mapping[str, Any]],
    survey: Mapping[str, SurveyPose],
    projector: LocalProjector,
) -> dict[str, dict[str, Any]]:
    """Move every adjusted scene; add the ones the survey placed from scratch."""
    result = {scene: dict(record) for scene, record in posed.items()}
    for scene, pose in survey.items():
        lng, lat = projector.to_wgs84(pose.x, pose.y)
        record = result.setdefault(scene, {"height_m": pose.z})
        record.update(
            x=pose.x,
            y=pose.y,
            lat=lat,
            lng=lng,
            heading_deg=pose.heading_deg,
            pose_source="surveyed" if pose.surveyed else "sfm",
        )
    return result
