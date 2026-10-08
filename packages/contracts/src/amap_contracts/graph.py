"""Walking-graph contract shared by the pipeline (producer), API and web app.

Serialized as GeoJSON: nodes are Point features (lng, lat, alt), edges are
LineString features. ``heading_deg`` is the compass bearing (clockwise from
true north) of panorama yaw 0, i.e. the centre of the front cube face, so a
hotspot at krpano ``ath`` points to ``(ath + heading_deg) % 360``.

Indoor panoramas have no measured position: they hang off the walking network
through the tour's links and stand at the measured node they hang off
(``Node.anchor``), so straight-line distances never overestimate a walk.
Clients must not draw them as places of their own; their edges carry
estimated lengths (``LengthSource.ESTIMATE``), and ``Edge.passage`` marks the
walks through a building between two different places. Every field added for
indoor routing is optional, so older readers keep parsing newer graphs.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

WALKING_SPEED_MPS = 1.3
GRAPH_SCHEMA_VERSION = 1
# A tour link this many storeys between two rooms of known floor is a menu
# jump in the tour, not a staircase: a passage (stairs cost and a penalty).
MENU_JUMP_FLOORS = 4


class NodeKind(StrEnum):
    OUTDOOR = "outdoor"
    ENTRANCE = "entrance"
    INDOOR = "indoor"


class EdgeCrossing(StrEnum):
    """What a drawn walking line passes through besides open ground."""

    SOFT = "soft"  # café seating, hedges, benches: walked through when needed
    BARRIER = "barrier"  # a wall or fence with no flight or gate noted there


class EdgeKind(StrEnum):
    OUTDOOR = "outdoor"
    ENTRANCE = "entrance"
    INDOOR = "indoor"
    STAIRS = "stairs"
    ELEVATOR = "elevator"


class PoseSource(StrEnum):
    SFM = "sfm"
    POSE_GRAPH = "pose_graph"
    # Not measured: derived from linked panoramas (indoor nodes, see anchor).
    INTERPOLATED = "interpolated"
    # Placed by hand where the SfM model put it wrong (configs/pose_overrides.toml).
    MANUAL = "manual"
    # Measured by the panorama survey: bearings to landmarks seen in the picture,
    # adjusted together with every other pose (configs/survey.toml).
    SURVEYED = "surveyed"


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
    floor: int | None = Field(
        default=None, description="Storey (0 = ground, negative = basement)"
    )
    anchor: str | None = Field(
        default=None,
        description=(
            "Measured node whose position this node borrows (indoor spots "
            "reached through tour links); None = the position is measured"
        ),
    )

    @property
    def approximate(self) -> bool:
        """The position is borrowed from ``anchor``, not measured."""
        return self.anchor is not None

    @property
    def level(self) -> int | None:
        """Storey for vertical moves: the floor, or 0 outdoors; None if unknown."""
        if self.floor is not None:
            return self.floor
        return 0 if self.kind is NodeKind.OUTDOOR else None


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
    # Walking line in local metres [east, north] from source to target, when
    # it bends around buildings; None = the straight segment between nodes.
    path_enu: list[tuple[float, float]] | None = None
    # Panorama yaw (degrees clockwise from the front cube face) that looks
    # along the edge: at the source towards the target, and at the target
    # towards the source. From the tour's hotspots; set where positions
    # cannot tell (indoor edges), None when the tour has no hotspot there.
    source_yaw_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    target_yaw_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    # A walk through a building between two places the map knows (a door and
    # another door, or a room off another door): the tour links them, but no
    # line outside does. Clients must not draw it; routes avoid it when they can.
    passage: bool = False
    # The drawn line crosses seating or a hedge, or (a walk the tour proves
    # where the notebook has no flight or gate) a wall or the fence. Routes
    # prefer edges without one; the walking time is unchanged.
    crosses: EdgeCrossing | None = None


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

    def to_geojson(
        self, to_lnglat: Callable[[float, float], tuple[float, float]] | None = None
    ) -> dict[str, Any]:
        """GeoJSON; ``to_lnglat`` (local metres -> lng, lat) draws bent edges."""
        coords = {n.id: (n.lng, n.lat, n.alt_m) for n in self.nodes}

        def line(e: Edge) -> list[list[float]]:
            ends = [list(coords[e.source]), list(coords[e.target])]
            if e.path_enu is None or to_lnglat is None or len(e.path_enu) < 3:
                return ends
            inner = [list(to_lnglat(x, y)) for x, y in e.path_enu[1:-1]]
            return [ends[0], *inner, ends[1]]

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
                "geometry": {"type": "LineString", "coordinates": line(e)},
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
