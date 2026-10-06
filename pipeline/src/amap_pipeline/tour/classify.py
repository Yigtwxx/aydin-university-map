"""Classify scenes as outdoor, entrance or indoor and select the Florya subset."""

import tomllib
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path

from amap_contracts import FLORYA_BBOX, search_key
from amap_pipeline.tour.parse import Scene


class SceneKind(StrEnum):
    OUTDOOR = "outdoor"
    ENTRANCE = "entrance"
    INDOOR = "indoor"


# Matched against whole tokens of search_key(label_tr).
_OUTDOOR_TOKENS = frozenset({"kampus", "bahce", "otopark", "meydan"})
_ENTRANCE_TOKENS = frozenset({"giris", "girisi"})
# "Giriş Kat" means ground floor, i.e. an indoor scene.
_GROUND_FLOOR = "giris kat"


def is_florya(scene: Scene) -> bool:
    return scene.meta is not None and FLORYA_BBOX.contains(
        scene.meta.lat, scene.meta.lng
    )


def classify(
    scene: Scene, overrides: Mapping[str, SceneKind] | None = None
) -> SceneKind:
    """Keyword rule on the TR label; ``overrides`` (by scene name) win."""
    if overrides and scene.name in overrides:
        return overrides[scene.name]
    if scene.meta is None:
        return SceneKind.INDOOR
    key = search_key(scene.meta.label_tr)
    tokens = set(key.split())
    if _GROUND_FLOOR in key:
        return SceneKind.INDOOR
    if tokens & _ENTRANCE_TOKENS:
        return SceneKind.ENTRANCE
    if tokens & _OUTDOOR_TOKENS:
        return SceneKind.OUTDOOR
    return SceneKind.INDOOR


def load_overrides(path: Path | None) -> dict[str, SceneKind]:
    """Read ``[overrides] scene_name = "outdoor"`` entries from a TOML file."""
    if path is None or not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw = data.get("overrides", {})
    if not isinstance(raw, dict):
        raise ValueError(f"[overrides] must be a table in {path}")
    return {str(name): SceneKind(str(kind)) for name, kind in raw.items()}


def florya_scenes(scenes: Iterable[Scene]) -> list[Scene]:
    return [s for s in scenes if is_florya(s)]
