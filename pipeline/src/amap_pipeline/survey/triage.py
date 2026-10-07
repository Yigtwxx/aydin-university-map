"""Ranked worklist for the panorama survey, from data alone (no images).

Four checks point at the panoramas whose placement deserves a look:

* Hotspot residuals. A tour arrow at krpano ``ath`` points at the scene it
  links to, ``(ath + heading_deg) % 360`` (see ``amap_contracts.graph``).
  Within one SfM model this does not depend on the georeference, so a large
  median exposes a distorted model. Per scene, a consistent offset with little
  spread is a wrong heading; a large spread is a wrong position.
  The tour's arrows are hand-placed and only roughly aimed, so these are weak
  evidence, never proof.
* Coarse offsets. The tour's own lat/lng is one point per building or area
  (most scenes share the campus default). Far from the pose, it hints that
  the area or the pose is wrong.
* Cameras inside footprints. A panorama stands outdoors or in a doorway.
* Unposed scenes. Outdoor panoramas and entrances without a measured pose.

Plus a signage index from the Gemini descriptions (``data/rag/vision.jsonl``):
which panoramas read which shop or block names, the worklist for storefronts.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from shapely import STRtree
from shapely.geometry import Point, Polygon

from amap_contracts.text import search_key
from amap_pipeline.geo.angles import circular_mean, compass_bearing, wrap180

MEASURED = frozenset({"sfm", "manual", "surveyed"})
# Links longer than this are tour teleports, not lines of sight.
MAX_LINK_M = 60.0
# Closer than this, a few decimetres of position error swamp the bearing.
MIN_LINK_M = 3.0
# Scenes this close to the tour's campus-wide default point carry no location.
DEFAULT_RADIUS_M = 15.0
HEADING_OFFSET_DEG = 10.0  # |mean residual| that suggests a wrong heading
HEADING_SPREAD_DEG = 8.0  # ... when the residuals agree this well
POSITION_SPREAD_DEG = 15.0  # spread that suggests a wrong position


@dataclass(frozen=True, slots=True)
class PosedScene:
    id: str
    kind: str  # outdoor | entrance | indoor
    x: float  # local metres east
    y: float  # local metres north
    heading_deg: float
    pose_source: str
    label: str
    area: str
    model: str | None  # "m0", ...; None when no SfM model holds the scene


@dataclass(frozen=True, slots=True)
class LinkResidual:
    source: str
    target: str
    distance_m: float
    observed_deg: float  # bearing of the tour's arrow
    predicted_deg: float  # bearing from the source's pose to the target's
    residual_deg: float  # observed - predicted, folded to ±180
    same_model: bool  # both ends in one SfM model: independent of georef


@dataclass(frozen=True, slots=True)
class SceneStats:
    scene: str
    links: int
    median_abs_deg: float
    mean_deg: float  # circular mean of the signed residuals
    spread_deg: float  # median |residual - mean|
    verdict: str  # ok | heading | position | few


@dataclass(frozen=True, slots=True)
class CoarseOffset:
    scene: str
    area: str
    dx: float  # tour point minus pose, metres east
    dy: float
    distance_m: float


def hotspot_residuals(
    posed: Mapping[str, PosedScene],
    link_yaw: Mapping[str, Mapping[str, float]],
    *,
    skip: Iterable[frozenset[str]] = (),
    max_link_m: float = MAX_LINK_M,
    min_link_m: float = MIN_LINK_M,
) -> list[LinkResidual]:
    """Every tour arrow between two measured, non-indoor scenes."""
    skipped = set(skip)
    out: list[LinkResidual] = []
    for source, yaws in sorted(link_yaw.items()):
        a = posed.get(source)
        if a is None or a.pose_source not in MEASURED or a.kind == "indoor":
            continue
        for target, ath in sorted(yaws.items()):
            b = posed.get(target)
            if b is None or b.pose_source not in MEASURED or b.kind == "indoor":
                continue
            if frozenset((source, target)) in skipped:
                continue
            dx, dy = b.x - a.x, b.y - a.y
            distance = math.hypot(dx, dy)
            if not min_link_m <= distance <= max_link_m:
                continue
            observed = (ath + a.heading_deg) % 360.0
            predicted = compass_bearing(dx, dy)
            out.append(
                LinkResidual(
                    source=source,
                    target=target,
                    distance_m=round(distance, 2),
                    observed_deg=round(observed, 2),
                    predicted_deg=round(predicted, 2),
                    residual_deg=round(wrap180(observed - predicted), 2),
                    same_model=(
                        a.model is not None
                        and a.model == b.model
                        and a.pose_source == b.pose_source == "sfm"
                    ),
                )
            )
    return out


def scene_stats(residuals: Sequence[LinkResidual]) -> list[SceneStats]:
    """Per source scene: is its heading or its position the likelier error?"""
    by_scene: dict[str, list[float]] = defaultdict(list)
    for r in residuals:
        by_scene[r.source].append(r.residual_deg)
    stats: list[SceneStats] = []
    for scene, values in by_scene.items():
        mean = circular_mean(values)
        spread = statistics.median(abs(wrap180(v - mean)) for v in values)
        median_abs = statistics.median(abs(v) for v in values)
        if len(values) < 2:
            verdict = "few" if median_abs > HEADING_OFFSET_DEG else "ok"
        elif abs(mean) > HEADING_OFFSET_DEG and spread <= HEADING_SPREAD_DEG:
            verdict = "heading"
        elif spread > POSITION_SPREAD_DEG:
            verdict = "position"
        else:
            verdict = "ok"
        stats.append(
            SceneStats(
                scene=scene,
                links=len(values),
                median_abs_deg=round(median_abs, 1),
                mean_deg=round(mean, 1),
                spread_deg=round(spread, 1),
                verdict=verdict,
            )
        )
    return sorted(stats, key=lambda s: -s.median_abs_deg)


def model_stats(
    residuals: Sequence[LinkResidual], posed: Mapping[str, PosedScene]
) -> dict[str, dict[str, float]]:
    """Per SfM model, over links inside it: does the model hold together?"""
    by_model: dict[str, list[float]] = defaultdict(list)
    for r in residuals:
        model = posed[r.source].model
        if r.same_model and model is not None:
            by_model[model].append(abs(r.residual_deg))
    return {
        model: {
            "links": len(values),
            "median_abs_deg": round(statistics.median(values), 1),
            "p90_abs_deg": round(_quantile(values, 0.9), 1),
        }
        for model, values in sorted(by_model.items())
    }


def coarse_offsets(
    posed: Mapping[str, PosedScene],
    coarse_xy: Mapping[str, tuple[float, float]],
    default_xy: tuple[float, float],
    *,
    default_radius_m: float = DEFAULT_RADIUS_M,
) -> list[CoarseOffset]:
    """Tour point minus pose for measured scenes whose tour point means something."""
    out: list[CoarseOffset] = []
    for scene, (cx, cy) in sorted(coarse_xy.items()):
        p = posed.get(scene)
        if p is None or p.pose_source not in MEASURED:
            continue
        if math.dist((cx, cy), default_xy) <= default_radius_m:
            continue
        dx, dy = cx - p.x, cy - p.y
        out.append(
            CoarseOffset(
                scene=scene,
                area=p.area,
                dx=round(dx, 1),
                dy=round(dy, 1),
                distance_m=round(math.hypot(dx, dy), 1),
            )
        )
    return out


def area_offsets(offsets: Sequence[CoarseOffset]) -> dict[str, dict[str, float]]:
    """Median tour-minus-pose vector per area: one wrong area moves as a block."""
    by_area: dict[str, list[CoarseOffset]] = defaultdict(list)
    for o in offsets:
        by_area[o.area].append(o)
    return {
        area: {
            "scenes": len(items),
            "dx": round(statistics.median(o.dx for o in items), 1),
            "dy": round(statistics.median(o.dy for o in items), 1),
            "median_distance_m": round(
                statistics.median(o.distance_m for o in items), 1
            ),
        }
        for area, items in sorted(by_area.items(), key=lambda kv: kv[0])
    }


def cameras_inside(
    posed: Mapping[str, PosedScene],
    outlines: Sequence[tuple[str, Polygon]],
    *,
    margin_m: float = 0.5,
) -> list[dict[str, Any]]:
    """Measured outdoor panoramas and entrances standing inside a footprint."""
    tree = STRtree([poly for _, poly in outlines])
    hits: list[dict[str, Any]] = []
    for scene in sorted(posed):
        p = posed[scene]
        if p.pose_source not in MEASURED or p.kind == "indoor":
            continue
        point = Point(p.x, p.y)
        for index in tree.query(point, predicate="within"):
            building, poly = outlines[int(index)]
            depth = poly.exterior.distance(point)
            if depth > margin_m:
                hits.append(
                    {
                        "scene": scene,
                        "building": building,
                        "depth_m": round(depth, 1),
                    }
                )
    return hits


def unposed_scenes(
    scenes: Sequence[Mapping[str, Any]], posed: Mapping[str, PosedScene]
) -> list[dict[str, str]]:
    """Outdoor panoramas and entrances with no measured pose (or not in the graph)."""
    out: list[dict[str, str]] = []
    for s in scenes:
        if s["kind"] == "indoor":
            continue
        p = posed.get(s["name"])
        if p is not None and p.pose_source in MEASURED:
            continue
        out.append(
            {
                "scene": s["name"],
                "kind": s["kind"],
                "label": s["label"]["tr"],
                "area": s["area"]["tr"],
                "status": "not in graph" if p is None else p.pose_source,
            }
        )
    return out


def signage_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Normalised sign text -> scenes whose description reads it."""
    index: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for text in row.get("signage_text") or []:
            key = search_key(str(text))
            if key:
                index[key].add(str(row["scene"]))
    return {key: sorted(scenes) for key, scenes in sorted(index.items())}


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass(frozen=True, slots=True)
class Triage:
    models: dict[str, dict[str, float]]
    scenes: list[SceneStats]
    links: list[LinkResidual]
    areas: dict[str, dict[str, float]]
    offsets: list[CoarseOffset]
    inside: list[dict[str, Any]]
    unposed: list[dict[str, str]]
    signage: dict[str, list[str]]

    def to_json(self) -> dict[str, Any]:
        return {
            "models": self.models,
            "scenes": [asdict(s) for s in self.scenes],
            "links": [asdict(r) for r in self.links],
            "areas": self.areas,
            "offsets": [asdict(o) for o in self.offsets],
            "inside": self.inside,
            "unposed": self.unposed,
            "signage": self.signage,
        }


def build_triage(
    posed: Mapping[str, PosedScene],
    scenes: Sequence[Mapping[str, Any]],
    coarse_xy: Mapping[str, tuple[float, float]],
    default_xy: tuple[float, float],
    outlines: Sequence[tuple[str, Polygon]],
    vision_rows: Iterable[Mapping[str, Any]],
    *,
    skip_links: Iterable[frozenset[str]] = (),
) -> Triage:
    link_yaw = {s["name"]: s.get("link_yaw", {}) for s in scenes}
    residuals = hotspot_residuals(posed, link_yaw, skip=skip_links)
    offsets = coarse_offsets(posed, coarse_xy, default_xy)
    return Triage(
        models=model_stats(residuals, posed),
        scenes=scene_stats(residuals),
        links=residuals,
        areas=area_offsets(offsets),
        offsets=offsets,
        inside=cameras_inside(posed, outlines),
        unposed=unposed_scenes(scenes, posed),
        signage=signage_index(vision_rows),
    )


def render_markdown(
    triage: Triage,
    posed: Mapping[str, PosedScene],
    labels: Mapping[str, str],
    *,
    outdoor: frozenset[str] = frozenset(),
) -> str:
    """Human-readable worklist; ``labels`` names scenes, ``outdoor`` filters signs."""

    def name(scene: str) -> str:
        return f"{scene} ({labels.get(scene, '?')})"

    lines = ["# Survey triage", ""]
    lines += [
        "## SfM models: tour arrows inside each model",
        "",
        "| model | links | median abs ° | p90 abs ° |",
        "|---|---|---|---|",
    ]
    for model, m in triage.models.items():
        lines.append(
            f"| {model} | {m['links']:.0f} | {m['median_abs_deg']} "
            f"| {m['p90_abs_deg']} |"
        )
    flagged = [s for s in triage.scenes if s.verdict != "ok"]
    lines += [
        "",
        "## Scenes whose arrows disagree",
        "",
        "`heading`: residuals agree on an offset (turn the panorama by -mean). "
        "`position`: residuals scatter (the camera is elsewhere). "
        "`few`: one arrow only.",
        "",
        "| scene | source | model | links | median abs ° | mean ° | spread ° "
        "| verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in flagged:
        p = posed[s.scene]
        lines.append(
            f"| {name(s.scene)} | {p.pose_source} | {p.model or '-'} | {s.links} | "
            f"{s.median_abs_deg} | {s.mean_deg} | {s.spread_deg} | {s.verdict} |"
        )
    lines += [
        "",
        "## Tour point minus pose, per area",
        "",
        "| area | scenes | dx m | dy m | median distance m |",
        "|---|---|---|---|---|",
    ]
    for area, a in sorted(
        triage.areas.items(), key=lambda kv: -kv[1]["median_distance_m"]
    ):
        lines.append(
            f"| {area} | {a['scenes']:.0f} | {a['dx']} | {a['dy']} | "
            f"{a['median_distance_m']} |"
        )
    lines += ["", "## Cameras inside a footprint", ""]
    lines += [
        f"- {name(h['scene'])}: {h['depth_m']} m inside {h['building']}"
        for h in triage.inside
    ] or ["- none"]
    lines += ["", "## Outdoor scenes and entrances without a measured pose", ""]
    lines += [
        f"- {u['scene']} {u['kind']} ({u['label']} / {u['area']}): {u['status']}"
        for u in triage.unposed
    ] or ["- none"]
    lines += ["", "## Signs read from outdoor panoramas and entrances", ""]
    for key, scenes in triage.signage.items():
        seen = [s for s in scenes if s in outdoor] if outdoor else list(scenes)
        if seen:
            lines.append(f"- **{key}**: {', '.join(seen)}")
    return "\n".join(lines) + "\n"
