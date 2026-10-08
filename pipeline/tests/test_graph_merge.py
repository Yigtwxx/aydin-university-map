"""Merging per-model georeferences into one set of node poses."""

from datetime import UTC, datetime
from typing import Any

from amap_contracts.graph import (
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
from amap_pipeline.commands.graph import main_network, merge_poses, trusted


def _georef(rms: float, scenes: dict[str, float], inside: int = 0) -> dict[str, Any]:
    return {
        "quality": {
            "icp_rms_m": rms,
            "cameras_inside_buildings": [f"s{i}" for i in range(inside)],
        },
        "scenes": {name: {"x": x} for name, x in scenes.items()},
    }


def test_trusted_rejects_poor_fit_and_cameras_inside_buildings() -> None:
    assert trusted(_georef(0.7, {"a": 0, "b": 1})), "good fit is trusted"
    assert not trusted(_georef(3.0, {"a": 0})), "ICP RMS above 2.5 m is rejected"
    many = {f"s{i}": float(i) for i in range(10)}
    assert not trusted(_georef(0.7, many, inside=3)), "30% inside buildings rejected"


def test_merge_poses_prefers_the_better_model_per_scene() -> None:
    worse = _georef(1.8, {"shared": 1.0, "only_worse": 2.0})
    better = _georef(0.6, {"shared": 9.0})
    merged = merge_poses([worse, better])
    assert merged["shared"]["x"] == 9.0, "lower RMS model wins a shared scene"
    assert merged["only_worse"]["x"] == 2.0, "scenes from other models stay"


def test_merge_poses_ignores_untrusted_models() -> None:
    merged = merge_poses([_georef(5.0, {"a": 1.0})])
    assert merged == {}, "an untrusted model contributes nothing"


def _place(name: str, kind: NodeKind, anchor: str | None = None) -> Node:
    text = LocalizedText(tr=name, en=name)
    return Node(
        id=name,
        kind=kind,
        lat=40.99,
        lng=28.79,
        alt_m=1.6,
        enu=(0.0, 0.0, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.INTERPOLATED if anchor else PoseSource.SURVEYED,
        label=text,
        area=text,
        anchor=anchor,
    )


def _walk(a: str, b: str) -> Edge:
    return Edge(
        id=f"{a}|{b}",
        source=a,
        target=b,
        kind=EdgeKind.OUTDOOR,
        origin=EdgeOrigin.TOUR,
        length_m=10.0,
        cost_s=8.0,
        length_source=LengthSource.ESTIMATE,
    )


def _campus_with_islands() -> Graph:
    """Campus a-b-c; a dorm (door + room) and a stray pair cut off from it."""
    nodes = [
        _place("a", NodeKind.OUTDOOR),
        _place("b", NodeKind.OUTDOOR),
        _place("c", NodeKind.ENTRANCE),
        _place("dorm_door", NodeKind.ENTRANCE),
        _place("dorm_room", NodeKind.INDOOR, anchor="dorm_door"),
        _place("stray", NodeKind.OUTDOOR),
        _place("stray_room", NodeKind.ENTRANCE, anchor="stray"),
    ]
    edges = [
        _walk("a", "b"),
        _walk("b", "c"),
        _walk("dorm_door", "dorm_room"),
        _walk("stray", "stray_room"),
    ]
    meta = GraphMeta(
        generated_at=datetime(2026, 10, 8, tzinfo=UTC),
        run_id="test",
        origin_lat=40.99,
        origin_lng=28.79,
    )
    return Graph(meta=meta, nodes=nodes, edges=edges)


def test_main_network_keeps_a_separate_site_with_a_measured_door() -> None:
    kept, _, sites = main_network(_campus_with_islands())
    ids = {n.id for n in kept.nodes}
    assert {"dorm_door", "dorm_room"} <= ids, f"the dorm must stay, got {ids}"
    assert "dorm_door|dorm_room" in {e.id for e in kept.edges}, "dorm keeps its edge"
    assert sites == [["dorm_door", "dorm_room"]], f"dorm is a site, got {sites}"


def test_main_network_drops_an_island_without_a_measured_door() -> None:
    kept, islands, _ = main_network(_campus_with_islands())
    ids = {n.id for n in kept.nodes}
    assert not ids & {"stray", "stray_room"}, f"stray island must go, got {ids}"
    assert islands == [["stray", "stray_room"]], f"reported as island: {islands}"


def test_main_network_leaves_a_connected_graph_alone() -> None:
    graph = _campus_with_islands()
    campus = graph.model_copy(
        update={"nodes": graph.nodes[:3], "edges": graph.edges[:2]}
    )
    kept, islands, sites = main_network(campus)
    assert kept == campus, "a single component is returned unchanged"
    assert islands == [] and sites == [], "nothing dropped or kept aside"
