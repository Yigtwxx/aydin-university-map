"""Survey notebook: named landmarks and what each panorama sees of them.

``configs/survey.toml``::

    tripod_m = 1.6

    # A physical point seen from several panoramas. ``xy`` (local metres) or an
    # OSM corner "CODE#i" by name; ``sigma_m`` is how far the prior may be off;
    # ``free = true`` drops the prior (a shop front nobody mapped).
    [landmarks."A#1"]
    sigma_m = 1.0
    [landmarks."E.door"]
    xy = [-21.5, -45.0]
    free = true

    # One table per panorama: what it sees (``ath`` in the panorama's own
    # degrees, so it does not depend on the pose being measured) and, for a
    # panorama no model placed well, ``pose = "free"`` with a starting guess.
    [scenes.scene_428538]
    pose = "free"
    init = [-20.0, -48.0, 10.0]   # x, y, heading
    prior_sigma_m = 8.0
    obs = [
      { lm = "E.door", ath = 101.4, snapped = true },
      { lm = "A#1", ath = 40.2 },
    ]
    note = "E's glass door straight ahead; A's corner over the hedge"

Landmark names ``CODE#i`` without ``xy`` resolve to vertex ``i`` of the
building whose overlay code is ``CODE`` (``amap look`` prints these labels).
Any other name a sighting uses is a tie point: a door jamb, pillar or sign
with no prior, placed by the rays of two or more panoramas.
"""

import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amap_pipeline.look.camera import DEFAULT_TRIPOD_M
from amap_pipeline.look.context import BuildingShape

# One notebook per area (``survey/<area>.toml``), merged: a landmark name means
# the same point in every file, and a scene's sightings add up.
DEFAULT_SURVEY = Path(__file__).parents[3] / "configs" / "survey"
SNAPPED_SIGMA_DEG = 0.4  # an edge snapped by ``amap look snap``
ROUGH_SIGMA_DEG = 1.5  # read off the grid by eye
_CORNER = re.compile(r"^(?P<code>[^#\s]+)#(?P<vertex>\d+)$")


@dataclass(frozen=True, slots=True)
class Landmark:
    name: str
    x: float
    y: float
    sigma_m: float | None  # None = free (no position prior)
    source: str  # "xy" | "<building id>#<vertex>" | "tie" (x, y are NaN)


@dataclass(frozen=True, slots=True)
class Sighting:
    landmark: str
    ath_deg: float
    sigma_deg: float
    snapped: bool


@dataclass(frozen=True, slots=True)
class SceneNotes:
    scene: str
    free: bool  # solve its own pose instead of following its SfM model
    init: tuple[float, float, float] | None  # x, y, heading
    prior_sigma_m: float | None
    prior_sigma_deg: float | None
    sightings: list[Sighting] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True, slots=True)
class Survey:
    tripod_m: float
    landmarks: dict[str, Landmark]
    scenes: dict[str, SceneNotes]


def _corner(
    name: str, buildings: Sequence[BuildingShape]
) -> tuple[float, float, str] | None:
    match = _CORNER.match(name)
    if match is None:
        return None
    code, vertex = match.group("code"), int(match.group("vertex"))
    hits = [b for b in buildings if b.code == code or b.id == code]
    if not hits:
        # A corner named before the registry gave its building a block code.
        hits = [b for b in buildings if b.id.rsplit("/", 1)[-1][-4:] == code]
    if len(hits) != 1:
        raise ValueError(f"landmark {name}: {len(hits)} buildings carry code {code!r}")
    (b,) = hits
    if not 0 <= vertex < len(b.outline):
        raise ValueError(f"landmark {name}: {b.id} has {len(b.outline)} vertices")
    x, y = b.outline[vertex]
    return float(x), float(y), f"{b.id}#{vertex}"


def _landmark(
    name: str, entry: Mapping[str, Any], buildings: Sequence[BuildingShape]
) -> Landmark:
    free = bool(entry.get("free", False))
    sigma = None if free else float(entry.get("sigma_m", 1.0))
    if "xy" in entry:
        x, y = (float(v) for v in entry["xy"])
        return Landmark(name, x, y, sigma, "xy")
    corner = _corner(name, buildings)
    if corner is None:
        # A tie point (door jamb, pillar, sign): no prior, the sightings place it.
        return Landmark(name, math.nan, math.nan, None, "tie")
    x, y, source = corner
    return Landmark(name, x, y, sigma, source)


def parse_survey(data: Mapping[str, Any], buildings: Sequence[BuildingShape]) -> Survey:
    landmarks: dict[str, Landmark] = {
        str(name): _landmark(str(name), entry, buildings)
        for name, entry in data.get("landmarks", {}).items()
    }
    scenes: dict[str, SceneNotes] = {}
    for scene, entry in data.get("scenes", {}).items():
        sightings: list[Sighting] = []
        for obs in entry.get("obs", []):
            name = str(obs["lm"])
            if name not in landmarks:
                # Seen but not declared: an OSM corner with the default prior.
                landmarks[name] = _landmark(name, {}, buildings)
            snapped = bool(obs.get("snapped", False))
            default = SNAPPED_SIGMA_DEG if snapped else ROUGH_SIGMA_DEG
            sightings.append(
                Sighting(
                    landmark=name,
                    ath_deg=float(obs["ath"]) % 360.0,
                    sigma_deg=float(obs.get("sigma_deg", default)),
                    snapped=snapped,
                )
            )
        init = entry.get("init")
        if init is not None and len(init) != 3:
            raise ValueError(f"{scene}: init is [x, y, heading]")
        mode = str(entry.get("pose", "model"))
        if mode not in ("model", "free"):
            raise ValueError(f"{scene}: pose must be 'model' or 'free', got {mode!r}")
        scenes[str(scene)] = SceneNotes(
            scene=str(scene),
            free=mode == "free",
            init=(
                None
                if init is None
                else (float(init[0]), float(init[1]), float(init[2]) % 360.0)
            ),
            prior_sigma_m=(
                float(entry["prior_sigma_m"]) if "prior_sigma_m" in entry else None
            ),
            prior_sigma_deg=(
                float(entry["prior_sigma_deg"]) if "prior_sigma_deg" in entry else None
            ),
            sightings=sightings,
            note=str(entry.get("note", "")),
        )
    return Survey(
        tripod_m=float(data.get("tripod_m", DEFAULT_TRIPOD_M)),
        landmarks=landmarks,
        scenes=scenes,
    )


def merge_notebooks(
    documents: Sequence[tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Merge area notebooks; conflicting landmark definitions are an error."""
    merged: dict[str, Any] = {"landmarks": {}, "scenes": {}}
    for name, data in documents:
        if "tripod_m" in data:
            if "tripod_m" in merged and merged["tripod_m"] != data["tripod_m"]:
                raise ValueError(f"{name}: tripod_m differs from another notebook")
            merged["tripod_m"] = data["tripod_m"]
        for lm, entry in data.get("landmarks", {}).items():
            if lm in merged["landmarks"] and merged["landmarks"][lm] != entry:
                raise ValueError(f"{name}: landmark {lm} is defined differently")
            merged["landmarks"][lm] = entry
        for scene, entry in data.get("scenes", {}).items():
            if scene not in merged["scenes"]:
                merged["scenes"][scene] = dict(entry)
                continue
            current = merged["scenes"][scene]
            for key, value in entry.items():
                if key == "obs":
                    current["obs"] = [*current.get("obs", []), *value]
                elif key == "note":
                    current["note"] = " / ".join(
                        n for n in (current.get("note"), value) if n
                    )
                elif key in current and current[key] != value:
                    raise ValueError(f"{name}: {scene}.{key} conflicts")
                else:
                    current[key] = value
    return merged


def load_survey(
    buildings: Sequence[BuildingShape], path: Path | None = DEFAULT_SURVEY
) -> Survey:
    """Read one notebook file or every ``*.toml`` in a directory."""
    if path is None or not path.exists():
        return Survey(tripod_m=DEFAULT_TRIPOD_M, landmarks={}, scenes={})
    files = sorted(path.glob("*.toml")) if path.is_dir() else [path]
    documents = [(f.name, tomllib.loads(f.read_text("utf-8"))) for f in files]
    return parse_survey(merge_notebooks(documents), buildings)
