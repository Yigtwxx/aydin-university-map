from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    Edge,
    EdgeKind,
    EdgeOrigin,
    Graph,
    GraphMeta,
    LengthSource,
    LocalizedText,
    Node,
    NodeKind,
    PoseSource,
)


def _node(node_id: str, lng: float, heading: float = 10.0) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.OUTDOOR,
        lat=40.9915,
        lng=lng,
        alt_m=1.6,
        enu=(0.0, 0.0, 1.6),
        heading_deg=heading,
        pose_source=PoseSource.SFM,
        label=LocalizedText(tr="Kampüs", en="Campus"),
        area=LocalizedText(tr="Florya Kampüs", en="Florya Campus"),
    )


@pytest.fixture
def graph() -> Graph:
    edge = Edge(
        id="a|b",
        source="a",
        target="b",
        kind=EdgeKind.OUTDOOR,
        origin=EdgeOrigin.TOUR,
        length_m=12.5,
        cost_s=12.5 / WALKING_SPEED_MPS,
        length_source=LengthSource.SFM,
    )
    meta = GraphMeta(
        generated_at=datetime(2026, 10, 6, tzinfo=UTC),
        run_id="test",
        origin_lat=40.9915,
        origin_lng=28.7971,
    )
    return Graph(
        meta=meta, nodes=[_node("a", 28.7970), _node("b", 28.7972)], edges=[edge]
    )


def test_graph_geojson_round_trip_preserves_model(graph: Graph) -> None:
    restored = Graph.from_geojson(graph.to_geojson())
    assert restored == graph, "GeoJSON round trip must be lossless"


def test_graph_geojson_edge_line_joins_node_coordinates(graph: Graph) -> None:
    edge_feature = next(
        f
        for f in graph.to_geojson()["features"]
        if f["properties"]["feature"] == "edge"
    )
    coords = edge_feature["geometry"]["coordinates"]
    assert coords == [[28.7970, 40.9915, 1.6], [28.7972, 40.9915, 1.6]], f"Got {coords}"


@pytest.mark.parametrize("heading", [-1.0, 360.0])
def test_node_heading_out_of_range_raises_validation_error(heading: float) -> None:
    with pytest.raises(ValidationError):
        _node("x", 28.797, heading=heading)


def test_edge_non_positive_length_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Edge(
            id="x",
            source="a",
            target="b",
            kind=EdgeKind.OUTDOOR,
            origin=EdgeOrigin.INFERRED,
            length_m=0.0,
            cost_s=1.0,
            length_source=LengthSource.SFM,
        )


def _indoor(graph: Graph) -> Graph:
    """b's room r: no measured position, stands at b; reached by a stairs edge."""
    b = next(n for n in graph.nodes if n.id == "b")
    room = b.model_copy(
        update={
            "id": "r",
            "kind": NodeKind.INDOOR,
            "pose_source": PoseSource.INTERPOLATED,
            "anchor": "b",
            "floor": -1,
        }
    )
    stairs = Edge(
        id="b|r",
        source="b",
        target="r",
        kind=EdgeKind.STAIRS,
        origin=EdgeOrigin.TOUR,
        length_m=12.0,
        cost_s=12.0 / WALKING_SPEED_MPS + 15.0,
        length_source=LengthSource.ESTIMATE,
        target_yaw_deg=270.0,
    )
    return graph.model_copy(
        update={"nodes": [*graph.nodes, room], "edges": [*graph.edges, stairs]}
    )


def test_graph_geojson_round_trip_keeps_indoor_fields(graph: Graph) -> None:
    indoor = _indoor(graph)
    restored = Graph.from_geojson(indoor.to_geojson())
    assert restored == indoor, "anchor, floor and yaws must survive"
    room = next(n for n in restored.nodes if n.id == "r")
    assert room.approximate and room.anchor == "b", room


def test_graph_geojson_without_indoor_fields_still_parses(graph: Graph) -> None:
    data = graph.to_geojson()
    for feature in data["features"]:
        for key in ("anchor", "source_yaw_deg", "target_yaw_deg"):
            feature["properties"].pop(key, None)
    restored = Graph.from_geojson(data)  # a graph exported before indoor routing
    assert restored == graph, "older graphs parse unchanged"
    assert not any(n.approximate for n in restored.nodes), restored.nodes


@pytest.mark.parametrize(
    ("kind", "floor", "expected"),
    [
        (NodeKind.OUTDOOR, None, 0),  # outdoors is ground level
        (NodeKind.ENTRANCE, None, None),
        (NodeKind.ENTRANCE, 1, 1),
        (NodeKind.INDOOR, None, None),
        (NodeKind.INDOOR, -2, -2),
    ],
)
def test_node_level_is_floor_or_ground_outdoors(
    kind: NodeKind, floor: int | None, expected: int | None
) -> None:
    node = _node("x", 28.797).model_copy(update={"kind": kind, "floor": floor})
    assert node.level == expected, f"{kind} {floor}: {node.level}"


@pytest.mark.parametrize("yaw", [-1.0, 360.0])
def test_edge_yaw_out_of_range_raises_validation_error(yaw: float) -> None:
    with pytest.raises(ValidationError):
        Edge(
            id="a|b",
            source="a",
            target="b",
            kind=EdgeKind.INDOOR,
            origin=EdgeOrigin.TOUR,
            length_m=12.0,
            cost_s=9.0,
            length_source=LengthSource.ESTIMATE,
            source_yaw_deg=yaw,
        )


def test_surveyed_pose_source_round_trips(graph: Graph) -> None:
    surveyed = graph.nodes[0].model_copy(update={"pose_source": PoseSource.SURVEYED})
    data = graph.model_copy(update={"nodes": [surveyed, graph.nodes[1]]}).to_geojson()
    restored = Graph.from_geojson(data)
    assert restored.nodes[0].pose_source is PoseSource.SURVEYED, (
        f"Got {restored.nodes[0].pose_source}"
    )
