import json
from pathlib import Path

import numpy as np
import pytest

from amap_pipeline.survey.kroki import (
    Marker,
    apply,
    fit_homography,
    place,
    ransac,
    read_markers,
)

H = np.array([[0.4, 0.05, -30.0], [-0.02, -0.5, 80.0], [0.0002, 0.0004, 1.0]])


def _markers() -> tuple[list[Marker], dict[str, tuple[float, float]]]:
    uv = np.array(
        [[20, 30], [400, 50], [380, 300], [40, 280], [200, 160], [120, 90], [300, 210]],
        float,
    )
    xy = apply(H, uv)
    markers = [Marker(f"s{i}", u, v, "outdoor") for i, (u, v) in enumerate(uv)]
    return markers, {
        m.scene: (float(x), float(y)) for m, (x, y) in zip(markers, xy, strict=True)
    }


def test_homography_round_trip() -> None:
    markers, known = _markers()
    src = np.array([[m.u, m.v] for m in markers])
    dst = np.array([known[m.scene] for m in markers])
    h = fit_homography(src, dst)
    assert apply(h, src) == pytest.approx(dst, abs=1e-6)


def test_ransac_flags_a_misplaced_pose_and_places_unknown_markers() -> None:
    markers, known = _markers()
    truth_s6 = known.pop("s6")  # unknown: to be placed from the sketch
    known["s4"] = (known["s4"][0] + 45.0, known["s4"][1])  # a pose 45 m off
    fit = ransac(markers, known, threshold_m=3.0)
    assert "s4" not in fit.inliers
    assert fit.residuals["s4"] == pytest.approx(45.0, abs=0.5)
    placed = place(fit, markers)
    assert placed["s6"] == pytest.approx(truth_s6, abs=0.05)


def test_ransac_needs_four_known_markers() -> None:
    markers, known = _markers()
    with pytest.raises(ValueError, match="need 4"):
        ransac(markers, dict(list(known.items())[:3]))


def test_read_markers_centres_right_aligned_offsets(tmp_path: Path) -> None:
    path = tmp_path / "kroki.json"
    path.write_text(
        json.dumps(
            {
                "marker_px": 20,
                "views": {
                    "front": {
                        "layer_w": 600,
                        "markers": [
                            {
                                "scene": "scene_1",
                                "right": 5,
                                "top": 158,
                                "kind": "outdoor",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (m,) = read_markers(path)["front"]
    assert (m.u, m.v) == (585.0, 168.0)


def test_plan_view_fits_a_similarity_with_mirrored_y() -> None:
    # A plan drawn 2 px per metre, north up the page, origin at (100, 100).
    truth = {"a": (0.0, 0.0), "b": (10.0, 0.0), "c": (0.0, 20.0), "d": (5.0, 5.0)}
    markers = [
        Marker(s, 100 + 2 * x, 100 - 2 * y, "entrance") for s, (x, y) in truth.items()
    ]
    known = {s: truth[s] for s in ("a", "b", "c")}
    fit = ransac(markers, known, plan=True, threshold_m=0.5)
    assert sorted(fit.inliers) == ["a", "b", "c"]
    assert place(fit, markers)["d"] == pytest.approx((5.0, 5.0), abs=1e-6)
