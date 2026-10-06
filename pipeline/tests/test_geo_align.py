import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from amap_pipeline.geo.align import (
    Similarity2D,
    footprint_union,
    icp_refine,
    outline_score_raster,
    search,
    umeyama_2d,
)

TRUE = Similarity2D(yaw=math.radians(37.0), scale=7.0, shift=(12.0, -25.0))
BUILDINGS = [
    Polygon([(0, 0), (40, 0), (40, 12), (0, 12)]),
    Polygon([(0, 30), (12, 30), (12, 70), (0, 70)]),
    Polygon([(30, 40), (60, 40), (60, 50), (45, 50), (45, 65), (30, 65)]),  # L-shape
]


def _outline_samples(step: float = 0.5) -> np.ndarray:
    samples = []
    for poly in BUILDINGS:
        ring = poly.exterior
        for d in np.arange(0.0, ring.length, step):
            p = ring.interpolate(float(d))
            samples.append((p.x, p.y))
    return np.array(samples)


def _inverse(t: Similarity2D, xy: np.ndarray) -> np.ndarray:
    c, s = math.cos(t.yaw), math.sin(t.yaw)
    rot = np.array([[c, -s], [s, c]])
    return (xy - np.asarray(t.shift)) @ rot / t.scale


@pytest.fixture(scope="module")
def scene() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    outline = _outline_samples()
    walls_map = outline[::3] + rng.normal(0.0, 0.3, size=(len(outline[::3]), 2))
    cams_map = np.array([[20.0, 22.0], [25.0, 30.0], [20.0, 55.0], [50.0, 25.0]])
    return {
        "outline": outline,
        "walls": _inverse(TRUE, walls_map),
        "cams": _inverse(TRUE, cams_map),
    }


def test_umeyama_2d_recovers_known_similarity(scene: dict[str, np.ndarray]) -> None:
    src = scene["walls"]
    result = umeyama_2d(src, TRUE.apply(src))
    assert result.scale == pytest.approx(TRUE.scale), f"Got {result}"
    assert result.yaw == pytest.approx(TRUE.yaw), f"Got {result}"
    assert np.allclose(result.shift, TRUE.shift), f"Got {result}"


def test_search_finds_yaw_scale_and_shift(scene: dict[str, np.ndarray]) -> None:
    score_map = outline_score_raster(scene["outline"], (-40, -40, 100, 110), 0.5)
    candidates = search(
        scene["walls"],
        scene["cams"],
        score_map,
        footprint_union(BUILDINGS),
        scale_prior=TRUE.scale * 1.08,
        yaw_step_deg=2.0,
    )
    best = candidates[0].transform
    yaw_err = abs((math.degrees(best.yaw - TRUE.yaw) + 180) % 360 - 180)
    assert yaw_err <= 2.0, f"Yaw off by {yaw_err:.1f} deg: {best}"
    assert best.scale == pytest.approx(TRUE.scale, rel=0.1), f"Got {best}"
    assert candidates[0].cameras_inside == 0.0, "Cameras must stay outside buildings"
    moved = best.apply(scene["walls"])
    expected = TRUE.apply(scene["walls"])
    assert np.median(np.linalg.norm(moved - expected, axis=1)) < 3.0


def test_icp_refine_converges_from_coarse_candidate(
    scene: dict[str, np.ndarray],
) -> None:
    coarse = Similarity2D(TRUE.yaw + math.radians(1.5), TRUE.scale * 1.05, TRUE.shift)
    result = icp_refine(scene["walls"], scene["outline"], coarse)
    moved = result.transform.apply(scene["walls"])
    error = np.median(np.linalg.norm(moved - TRUE.apply(scene["walls"]), axis=1))
    assert error < 0.3, f"ICP residual {error:.2f} m: {result}"
    assert result.inlier_ratio > 0.9, f"Got inlier ratio {result.inlier_ratio}"
