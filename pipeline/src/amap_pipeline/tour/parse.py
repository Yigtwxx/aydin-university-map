"""Parse the krpano runtime dump of the 360 tour into typed scenes.

The dump (``data/raw/tour_scenes.json``) is a list of rows captured from the
running tour: ``[index, name, title, onstart, hotspots]`` where each hotspot is
``[name, linkedscene, ath, atv, bakacakyon, style]`` (all strings).

Scene metadata lives in the ``hedefibelirle(...)`` call inside ``onstart``.
Its 35 comma-separated parameters are:

====== ===============================================================
index  meaning
====== ===============================================================
0      scene id (numeric)
1      number of navigation links
2-7    link angles (ath), zero padded to 6
8-13   linked scene ids (short form), zero padded
14-19  sector mid angles used by the floating arrow
20-25  arrival headings (bakacakyon), zero padded
26-27  latitude, longitude (coarse: one point per building/area)
28     per-scene angle (possibly the pano compass heading; unverified)
29-30  place group id (repeated)
31-34  label TR, area TR, area EN, label EN (label EN may contain commas)
====== ===============================================================
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_HEDEF_RE = re.compile(r"hedefibelirle\(([^)]*)\)")
_MEKAN_RE = re.compile(r"mekanibelirle\((\d+)\)")
_FIXED_PARAMS = 34  # params before the (possibly comma-split) EN label


@dataclass(frozen=True, slots=True)
class Hotspot:
    name: str
    linked_scene: str
    ath: float | None
    arrival_heading: float | None


@dataclass(frozen=True, slots=True)
class SceneMeta:
    """Fields decoded from ``hedefibelirle(...)``."""

    lat: float
    lng: float
    angle_p28: float | None
    place_group: str
    label_tr: str
    area_tr: str
    area_en: str
    label_en: str


@dataclass(frozen=True, slots=True)
class Scene:
    index: int
    name: str
    title: str
    hotspots: tuple[Hotspot, ...]
    place_code: str | None
    meta: SceneMeta | None

    @property
    def nav_links(self) -> tuple[str, ...]:
        return tuple(h.linked_scene for h in self.hotspots if h.linked_scene)


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def parse_meta(onstart: str) -> SceneMeta | None:
    """Decode the ``hedefibelirle`` parameters, or ``None`` if absent/invalid."""
    match = _HEDEF_RE.search(onstart)
    if match is None:
        return None
    params = [p.strip() for p in match.group(1).split(",")]
    if len(params) <= _FIXED_PARAMS:
        return None
    lat, lng = _to_float(params[26]), _to_float(params[27])
    if lat is None or lng is None:
        return None
    return SceneMeta(
        lat=lat,
        lng=lng,
        angle_p28=_to_float(params[28]),
        place_group=params[29],
        label_tr=params[31],
        area_tr=params[32],
        area_en=params[33],
        label_en=", ".join(params[_FIXED_PARAMS:]),
    )


def parse_place_code(onstart: str) -> str | None:
    match = _MEKAN_RE.search(onstart)
    return match.group(1) if match else None


def parse_hotspot(row: Sequence[str]) -> Hotspot:
    name, linked, ath, _atv, arrival, _style = row
    return Hotspot(
        name=name,
        linked_scene=linked,
        ath=_to_float(ath),
        arrival_heading=_to_float(arrival),
    )


def parse_scene(row: Sequence[object]) -> Scene:
    index, name, title, onstart, hotspots = row
    if not isinstance(onstart, str) or not isinstance(hotspots, list):
        raise ValueError(f"Malformed scene row: {row!r:.120}")
    return Scene(
        index=int(str(index)),
        name=str(name),
        title=str(title),
        hotspots=tuple(parse_hotspot(h) for h in hotspots),
        place_code=parse_place_code(onstart),
        meta=parse_meta(onstart),
    )


def load_dump(path: Path) -> list[Scene]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [parse_scene(row) for row in rows]
