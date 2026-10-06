"""Walking-graph contract shared by the pipeline (producer), API and web app.

Serialized as GeoJSON: nodes are Point features (lng, lat, alt), edges are
LineString features. ``heading_deg`` is the compass bearing (clockwise from
true north) of panorama yaw 0, i.e. the centre of the front cube face, so a
hotspot at krpano ``ath`` points to ``(ath + heading_deg) % 360``.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

WALKING_SPEED_MPS = 1.3
GRAPH_SCHEMA_VERSION = 1


class NodeKind(StrEnum):
    OUTDOOR = "outdoor"
    ENTRANCE = "entrance"
    INDOOR = "indoor"


class EdgeKind(StrEnum):
    OUTDOOR = "outdoor"
    ENTRANCE = "entrance"
    INDOOR = "indoor"
    STAIRS = "stairs"
    ELEVATOR = "elevator"


class PoseSource(StrEnum):
    SFM = "sfm"
    POSE_GRAPH = "pose_graph"
    INTERPOLATED = "interpolated"


class LengthSource(StrEnum):
    SFM = "sfm"
    OSM = "osm"
    ESTIMATE = "estimate"


class EdgeOrigin(StrEnum):
    TOUR = "tour"  # a navigation link of the 360 tour, confirmed by SfM
    INFERRED = "inferred"  # line of sight between nearby panos, not in the tour


class LocalizedText(BaseModel):
    model_config = ConfigDict(frozen=True)

    tr: str
    en: str


class Node(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: NodeKind
    lat: float
    lng: float
    alt_m: float = Field(description="Camera height above local ground, metres")
    enu: tuple[float, float, float] = Field(
        description="Local metres from the campus origin: east, north, up"
    )
    heading_deg: float = Field(ge=0.0, lt=360.0)
    pose_source: PoseSource
    label: LocalizedText
    area: LocalizedText
    building: str | None = None
    floor: int | None = None


class Edge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    target: str
    kind: EdgeKind
    origin: EdgeOrigin
    length_m: float = Field(gt=0.0)
    cost_s: float = Field(gt=0.0)
    length_source: LengthSource
    bidirectional: bool = True


class GraphMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = GRAPH_SCHEMA_VERSION
    generated_at: datetime
    run_id: str
    origin_lat: float
    origin_lng: float
    crs: str = "EPSG:4326"


class Graph(BaseModel):
    model_config = ConfigDict(frozen=True)

    meta: GraphMeta
    nodes: list[Node]
    edges: list[Edge]

    def to_geojson(self) -> dict[str, Any]:
        coords = {n.id: (n.lng, n.lat, n.alt_m) for n in self.nodes}
        features: list[dict[str, Any]] = [
            {
                "type": "Feature",
                "id": n.id,
                "geometry": {"type": "Point", "coordinates": list(coords[n.id])},
                "properties": {"feature": "node", **n.model_dump(mode="json")},
            }
            for n in self.nodes
        ]
        features += [
            {
                "type": "Feature",
                "id": e.id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(coords[e.source]), list(coords[e.target])],
                },
                "properties": {"feature": "edge", **e.model_dump(mode="json")},
            }
            for e in self.edges
        ]
        return {
            "type": "FeatureCollection",
            "meta": self.meta.model_dump(mode="json"),
            "features": features,
        }

    @classmethod
    def from_geojson(cls, data: dict[str, Any]) -> "Graph":
        nodes: list[Node] = []
        edges: list[Edge] = []
        for feature in data["features"]:
            props = {k: v for k, v in feature["properties"].items() if k != "feature"}
            if feature["properties"]["feature"] == "node":
                nodes.append(Node.model_validate(props))
            else:
                edges.append(Edge.model_validate(props))
        return cls(
            meta=GraphMeta.model_validate(data["meta"]), nodes=nodes, edges=edges
        )
