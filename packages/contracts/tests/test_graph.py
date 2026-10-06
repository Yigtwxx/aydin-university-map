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
