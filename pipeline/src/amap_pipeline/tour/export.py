"""Serialize classified Florya scenes for downstream pipeline steps."""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amap_pipeline.tour.classify import SceneKind, classify, florya_scenes
from amap_pipeline.tour.parse import Scene
from amap_pipeline.tour.select import build_adjacency, connected_components


@dataclass(frozen=True, slots=True)
class ClassifiedTour:
    scenes: list[Scene]
    kinds: dict[str, SceneKind]
    adjacency: dict[str, set[str]]

    def names_of_kind(self, *kinds: SceneKind) -> set[str]:
        return {name for name, kind in self.kinds.items() if kind in kinds}


def classify_tour(
    scenes: list[Scene], overrides: Mapping[str, SceneKind] | None = None
) -> ClassifiedTour:
    """Keep Florya scenes, classify them and build their link graph."""
    florya = florya_scenes(scenes)
    return ClassifiedTour(
        scenes=florya,
        kinds={s.name: classify(s, overrides) for s in florya},
        adjacency=build_adjacency(florya),
    )


def scene_record(scene: Scene, tour: ClassifiedTour) -> dict[str, Any]:
    meta = scene.meta
    assert meta is not None, "Florya scenes always carry metadata"
    return {
        "name": scene.name,
        "index": scene.index,
        "kind": tour.kinds[scene.name].value,
        "lat": meta.lat,
        "lng": meta.lng,
        "angle_p28": meta.angle_p28,
        "place_group": meta.place_group,
        "label": {"tr": meta.label_tr, "en": meta.label_en},
        "area": {"tr": meta.area_tr, "en": meta.area_en},
        "links": sorted(tour.adjacency[scene.name]),
    }


def summary(tour: ClassifiedTour) -> dict[str, Any]:
    outdoor = tour.names_of_kind(SceneKind.OUTDOOR, SceneKind.ENTRANCE)
    outdoor_adj = {
        n: tour.adjacency[n] & outdoor for n in tour.adjacency if n in outdoor
    }
    return {
        "scenes": len(tour.scenes),
        "kinds": dict(Counter(k.value for k in tour.kinds.values())),
        "edges": sum(len(v) for v in tour.adjacency.values()) // 2,
        "components": [len(c) for c in connected_components(tour.adjacency)],
        "outdoor_components": [len(c) for c in connected_components(outdoor_adj)],
    }


def write_scenes(tour: ClassifiedTour, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    records = [scene_record(s, tour) for s in tour.scenes]
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
