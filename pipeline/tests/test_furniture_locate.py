import math

import pytest

from amap_pipeline.furniture.locate import cluster, place, triangulate, tripod_height
from amap_pipeline.look.camera import Pose, bearing_to_ath

TRIPOD = 1.6
POSES = {
    "a": Pose("a", 0.0, 0.0, 1.6, 30.0, TRIPOD),
    "b": Pose("b", 8.0, 0.0, 1.6, 300.0, TRIPOD),
    "c": Pose("c", 4.0, -6.0, 1.6, 0.0, TRIPOD),
}
BENCH = (4.0, 5.0)


def _detection(
    scene: str,
    target: tuple[float, float],
    kind: str = "bench",
    score: float = 0.5,
    true_height: float = TRIPOD,
) -> dict[str, object]:
    p = POSES[scene]
    dx, dy = target[0] - p.x, target[1] - p.y
    dist = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy)) % 360
    ath = bearing_to_ath(p, bearing)
    atv = math.degrees(math.atan2(true_height, dist))
    return {"scene": scene, "kind": kind, "score": score, "ath_deg": ath,
            "atv_bottom_deg": atv, "atv_top_deg": atv - 5, "ath_left_deg": ath - 3,
            "ath_right_deg": ath + 3}  # fmt: skip


def test_monoplot_places_a_detection_on_the_ground() -> None:
    (p,) = place([_detection("a", BENCH)], POSES)
    assert (p.x, p.y) == pytest.approx(BENCH, abs=1e-6)
    assert p.range_m == pytest.approx(math.hypot(*BENCH))


def test_low_scores_and_far_hits_are_dropped() -> None:
    assert place([_detection("a", BENCH, score=0.1)], POSES) == []
    assert place([_detection("a", (40.0, 40.0))], POSES) == []


def test_two_views_triangulate_without_the_camera_height() -> None:
    # The real tripod is 2.2 m: monoplot misplaces, bearings don't care.
    dets = [_detection(s, BENCH, true_height=2.2) for s in ("a", "b", "c")]
    placed = place(dets, POSES)
    tri = triangulate(placed, POSES)
    assert tri == pytest.approx(BENCH, abs=1e-6)
    (cand,) = cluster(placed, POSES)
    assert cand.method == "triangulated"
    assert sorted(cand.scenes) == ["a", "b", "c"]


def test_tripod_height_is_measured_from_triangulated_objects() -> None:
    targets = [(4.0, 5.0), (3.0, 3.0), (6.0, 4.0), (2.0, -3.0), (5.0, 2.0)]
    dets = [
        _detection(s, t, kind=k, true_height=2.1)
        for t, k in zip(
            targets, ["bench", "lamp", "bin", "planter", "bollard"], strict=True
        )
        for s in ("a", "b", "c")
    ]
    cands = cluster(place(dets, POSES), POSES)
    assert tripod_height(cands, POSES) == pytest.approx(2.1, abs=0.01)


def test_single_far_weak_detection_is_not_a_candidate() -> None:
    weak = _detection("a", (6.0, 9.0), score=0.3)
    assert cluster(place([weak], POSES), POSES) == []
