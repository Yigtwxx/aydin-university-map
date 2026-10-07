"""What the look tool knows about the campus: poses, buildings, tour links."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from amap_contracts.graph import Graph
from amap_pipeline.look.camera import DEFAULT_TRIPOD_M, FloatArray, Pose
from amap_pipeline.look.render import FaceCache

_BLOCK = re.compile(r"Aydın Üniversitesi ([A-Z]{1,2}) Binası")


@dataclass(frozen=True, slots=True)
class BuildingShape:
    id: str
    name: str | None
    code: str  # short tag for overlays: the block letter or the id's tail
    outline: FloatArray  # (N, 2) local metres, open ring
    height_m: float
    campus: bool


@dataclass(frozen=True, slots=True)
class GroundLine:
    kind: str
    line: FloatArray  # (N, 2)


@dataclass(slots=True)
class LookContext:
    poses: dict[str, Pose]
    pose_sources: dict[str, str]
    labels: dict[str, str]
    link_yaw: dict[str, dict[str, float]]
    buildings: list[BuildingShape]
    ground: list[GroundLine]
    faces: FaceCache
    extra: dict[str, Any] = field(default_factory=dict)

    def pose(self, scene: str) -> Pose | None:
        return self.poses.get(scene)

    def label(self, scene: str) -> str:
        return self.labels.get(scene, scene)

    def buildings_near(
        self, x: float, y: float, radius_m: float
    ) -> list[BuildingShape]:
        out: list[BuildingShape] = []
        for b in self.buildings:
            d = np.hypot(b.outline[:, 0] - x, b.outline[:, 1] - y)
            if float(d.min()) <= radius_m:
                out.append(b)
        return out


def building_code(building_id: str, name: str | None) -> str:
    if name:
        match = _BLOCK.search(name)
        if match:
            return match.group(1)
    return building_id.rsplit("/", 1)[-1][-4:]


def parse_buildings(data: Mapping[str, Any]) -> list[BuildingShape]:
    shapes: list[BuildingShape] = []
    for b in data["buildings"]:
        outline = np.asarray(b["outline"], dtype=np.float64)
        if len(outline) >= 2 and np.allclose(outline[0], outline[-1]):
            outline = outline[:-1]
        if len(outline) < 3:
            continue
        name = b.get("name")
        shapes.append(
            BuildingShape(
                id=str(b["id"]),
                name=name,
                code=str(b.get("code") or building_code(str(b["id"]), name)),
                outline=outline,
                height_m=float(b.get("height_m") or 10.0),
                campus=bool(b.get("campus")),
            )
        )
    return shapes


def poses_from_graph(
    graph: Graph, tripod_m: float = DEFAULT_TRIPOD_M
) -> tuple[dict[str, Pose], dict[str, str]]:
    poses: dict[str, Pose] = {}
    sources: dict[str, str] = {}
    for n in graph.nodes:
        poses[n.id] = Pose(
            scene=n.id,
            x=n.enu[0],
            y=n.enu[1],
            z=n.enu[2],
            heading_deg=n.heading_deg,
            tripod_m=tripod_m,
        )
        sources[n.id] = n.pose_source.value
    return poses, sources


def load_context(
    data_dir: Path, *, tripod_m: float = DEFAULT_TRIPOD_M, cache_scenes: int = 6
) -> LookContext:
    out = data_dir / "out"
    graph = Graph.from_geojson(json.loads((out / "graph.geojson").read_text("utf-8")))
    poses, sources = poses_from_graph(graph, tripod_m)
    scenes: list[dict[str, Any]] = json.loads(
        (data_dir / "derived" / "scenes.json").read_text("utf-8")
    )
    buildings = parse_buildings(json.loads((out / "buildings.json").read_text("utf-8")))
    ground: list[GroundLine] = []
    ground_path = out / "ground.json"
    if ground_path.is_file():
        for way in json.loads(ground_path.read_text("utf-8")).get("ways", []):
            ground.append(
                GroundLine(kind=str(way["kind"]), line=np.asarray(way["line"], float))
            )
    return LookContext(
        poses=poses,
        pose_sources=sources,
        labels={s["name"]: s["label"]["tr"] for s in scenes},
        link_yaw={s["name"]: dict(s.get("link_yaw", {})) for s in scenes},
        buildings=buildings,
        ground=ground,
        faces=FaceCache(
            [data_dir / "tiles", data_dir / "out" / "panos"], capacity=cache_scenes
        ),
    )
