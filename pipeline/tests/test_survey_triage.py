import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from shapely.geometry import box
from typer.testing import CliRunner

from amap_contracts.graph import (
    Graph,
    GraphMeta,
    LocalizedText,
    Node,
    NodeKind,
    PoseSource,
)
from amap_pipeline.cli import app
from amap_pipeline.geo.angles import circular_mean, compass_bearing, wrap180
from amap_pipeline.survey.triage import (
    PosedScene,
    build_triage,
    cameras_inside,
    coarse_offsets,
    hotspot_residuals,
    model_stats,
    render_markdown,
    scene_stats,
    signage_index,
    unposed_scenes,
)


def _posed(
    scene: str,
    x: float,
    y: float,
    heading: float = 0.0,
    *,
    kind: str = "outdoor",
    source: str = "sfm",
    model: str | None = "m0",
    area: str = "Kampüs",
) -> PosedScene:
    return PosedScene(
        id=scene,
        kind=kind,
        x=x,
        y=y,
        heading_deg=heading,
        pose_source=source,
        label=scene,
        area=area,
        model=model,
    )


def test_angles() -> None:
    assert wrap180(190.0) == pytest.approx(-170.0)
    assert wrap180(-180.0) == pytest.approx(-180.0)
    assert compass_bearing(1.0, 0.0) == pytest.approx(90.0)
    assert compass_bearing(0.0, -1.0) == pytest.approx(180.0)
    assert circular_mean([350.0, 10.0]) == pytest.approx(0.0, abs=1e-9)
    assert circular_mean([]) == 0.0


def test_residual_is_arrow_bearing_minus_pose_bearing() -> None:
    posed = {"a": _posed("a", 0, 0, heading=90.0), "b": _posed("b", 10, 0)}
    # ath 10 + heading 90 = arrow at 100°; b lies due east (90°).
    (r,) = hotspot_residuals(posed, {"a": {"b": 10.0}})
    assert r.observed_deg == pytest.approx(100.0)
    assert r.predicted_deg == pytest.approx(90.0)
    assert r.residual_deg == pytest.approx(10.0)
    assert r.same_model


def test_residuals_skip_teleports_unmeasured_and_menu_jumps() -> None:
    posed = {
        "a": _posed("a", 0, 0),
        "far": _posed("far", 0, 100),
        "near": _posed("near", 0, 1),
        "room": _posed("room", 0, 10, kind="indoor", source="interpolated"),
        "c": _posed("c", 10, 0, model="m1"),
        "d": _posed("d", -10, 0),
    }
    yaws = {"a": {"far": 0.0, "near": 0.0, "room": 0.0, "c": 90.0, "d": 270.0}}
    residuals = hotspot_residuals(posed, yaws, skip=[frozenset(("a", "d"))])
    assert [r.target for r in residuals] == ["c"]
    assert not residuals[0].same_model  # different models: georef-dependent


def test_scene_verdicts() -> None:
    posed = {
        "h": _posed("h", 0, 0),
        "p": _posed("p", 0, 0),
        "one": _posed("one", 0, 0),
        **{t: _posed(t, x, y) for t, x, y in [("n", 0, 10), ("e", 10, 0)]},
        "s": _posed("s", 0, -10),
        "w": _posed("w", -10, 0),
    }
    yaws = {
        # Every arrow 30° clockwise of its target: a wrong heading.
        "h": {"n": 30.0, "e": 120.0, "s": 210.0},
        # Arrows all over the place: a wrong position.
        "p": {"n": 60.0, "e": 50.0, "s": 300.0, "w": 270.0},
        "one": {"n": 45.0},
    }
    stats = {s.scene: s for s in scene_stats(hotspot_residuals(posed, yaws))}
    assert stats["h"].verdict == "heading"
    assert stats["h"].mean_deg == pytest.approx(30.0)
    assert stats["p"].verdict == "position"
    assert stats["one"].verdict == "few"


def test_model_stats_use_links_inside_one_model() -> None:
    posed = {
        "a": _posed("a", 0, 0),
        "b": _posed("b", 0, 10),
        "c": _posed("c", 10, 0, model="m1"),
    }
    residuals = hotspot_residuals(posed, {"a": {"b": 4.0, "c": 50.0}})
    assert model_stats(residuals, posed) == {
        "m0": {"links": 1, "median_abs_deg": 4.0, "p90_abs_deg": 4.0}
    }


def test_coarse_offsets_ignore_the_default_point() -> None:
    posed = {"a": _posed("a", 0, 0, area="T Blok"), "b": _posed("b", 5, 5)}
    offsets = coarse_offsets(posed, {"a": (3.0, -80.0), "b": (101.0, 99.0)}, (100, 100))
    (o,) = offsets
    assert (o.scene, o.dx, o.dy) == ("a", 3.0, -80.0)


def test_cameras_inside_skip_doorways() -> None:
    posed = {
        "deep": _posed("deep", 5, 5),
        "door": _posed("door", 0.2, 5, kind="entrance"),
        "out": _posed("out", 20, 5),
    }
    hits = cameras_inside(posed, [("way/1", box(0, 0, 10, 10))])
    assert hits == [{"scene": "deep", "building": "way/1", "depth_m": 5.0}]


def test_unposed_lists_interpolated_and_missing_scenes() -> None:
    scenes = [
        {"name": "a", "kind": "entrance", "label": {"tr": "A"}, "area": {"tr": "X"}},
        {"name": "b", "kind": "outdoor", "label": {"tr": "B"}, "area": {"tr": "X"}},
        {"name": "c", "kind": "indoor", "label": {"tr": "C"}, "area": {"tr": "X"}},
        {"name": "d", "kind": "outdoor", "label": {"tr": "D"}, "area": {"tr": "X"}},
    ]
    posed = {
        "a": _posed("a", 0, 0, kind="entrance", source="interpolated"),
        "d": _posed("d", 0, 0),
    }
    assert [(u["scene"], u["status"]) for u in unposed_scenes(scenes, posed)] == [
        ("a", "interpolated"),
        ("b", "not in graph"),
    ]


def test_signage_index_folds_turkish_case() -> None:
    rows = [
        {"scene": "s1", "signage_text": ["KÜTÜPHANE", "Burger King"]},
        {"scene": "s2", "signage_text": ["Kütüphane"]},
        {"scene": "s3", "signage_text": None},
    ]
    assert signage_index(rows) == {
        "burger king": ["s1"],
        "kutuphane": ["s1", "s2"],
    }


def test_markdown_lists_flagged_scenes_and_signs() -> None:
    posed = {"a": _posed("a", 0, 0), "b": _posed("b", 0, 10)}
    scenes = [
        {
            "name": "a",
            "kind": "outdoor",
            "label": {"tr": "Kampüs"},
            "area": {"tr": "Kampüs"},
            "link_yaw": {"b": 120.0},
        }
    ]
    triage = build_triage(
        posed,
        scenes,
        {},
        (0.0, 0.0),
        [],
        [{"scene": "a", "signage_text": ["Starbucks"]}],
    )
    text = render_markdown(triage, posed, {"a": "Kampüs"}, outdoor=frozenset({"a"}))
    assert "| a (Kampüs) | sfm | m0 | 1 | 120.0 |" in text
    assert "- **starbucks**: a" in text


def _node(scene: str, kind: NodeKind, x: float, y: float) -> Node:
    return Node(
        id=scene,
        kind=kind,
        lat=40.99,
        lng=28.79,
        alt_m=1.6,
        enu=(x, y, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.SFM,
        label=LocalizedText(tr=scene, en=scene),
        area=LocalizedText(tr="Kampüs", en="Campus"),
    )


def test_cli_writes_triage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAP_DATA_DIR", str(tmp_path))
    out = tmp_path / "out"
    out.mkdir()
    graph = Graph(
        meta=GraphMeta(
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            run_id="r",
            origin_lat=40.9915,
            origin_lng=28.7971,
        ),
        nodes=[
            _node("scene_1", NodeKind.OUTDOOR, 0, 0),
            _node("scene_2", NodeKind.ENTRANCE, 0, 10),
        ],
        edges=[],
    )
    (out / "graph.geojson").write_text(json.dumps(graph.to_geojson()), "utf-8")
    (out / "graph_report.json").write_text('{"menu_jumps": []}', "utf-8")
    (out / "buildings.json").write_text(
        json.dumps(
            {"buildings": [{"id": "way/1", "outline": [[50, 50], [60, 50], [60, 60]]}]}
        ),
        "utf-8",
    )
    derived = tmp_path / "derived"
    derived.mkdir()
    scenes = [
        {
            "name": f"scene_{i}",
            "kind": kind,
            "lat": 40.99147,
            "lng": 28.797111,
            "label": {"tr": f"S{i}", "en": f"S{i}"},
            "area": {"tr": "Kampüs", "en": "Campus"},
            "links": [],
            "link_yaw": {"scene_2": 40.0} if i == 1 else {},
        }
        for i, kind in [(1, "outdoor"), (2, "entrance")]
    ]
    (derived / "scenes.json").write_text(json.dumps(scenes), "utf-8")
    result = CliRunner().invoke(app, ["survey", "triage", "--run", "none"])
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "debug" / "survey" / "triage.json").read_text())
    assert payload["scenes"][0]["scene"] == "scene_1"
    assert payload["scenes"][0]["median_abs_deg"] == pytest.approx(40.0)
    assert (tmp_path / "debug" / "survey" / "triage.md").is_file()
