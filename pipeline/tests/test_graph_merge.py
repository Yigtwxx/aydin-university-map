"""Merging per-model georeferences into one set of node poses."""

from typing import Any

from amap_pipeline.commands.graph import merge_poses, trusted


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
