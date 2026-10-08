import math
from pathlib import Path

import numpy as np
import pytest

from amap_pipeline.geo.angles import compass_bearing
from amap_pipeline.look.context import BuildingShape
from amap_pipeline.survey.observations import (
    Landmark,
    SceneNotes,
    Sighting,
    Survey,
    load_survey,
    parse_survey,
)
from amap_pipeline.survey.solve import (
    PriorPose,
    SolveConfig,
    TourLink,
    holdout,
    solve_survey,
)

# Ground truth: four building corners and five panoramas between them.
CORNERS = {
    "A#0": (0.0, 40.0),
    "A#1": (40.0, 40.0),
    "B#0": (40.0, 0.0),
    "B#1": (0.0, 0.0),
}
TRUE = {
    "s1": (10.0, 10.0, 0.0),
    "s2": (20.0, 15.0, 45.0),
    "s3": (30.0, 20.0, 90.0),
    "s4": (15.0, 30.0, 200.0),
    "s5": (25.0, 25.0, 300.0),
}


def _ath(scene: tuple[float, float, float], target: tuple[float, float]) -> float:
    x, y, h = scene
    return (compass_bearing(target[0] - x, target[1] - y) - h) % 360.0


def _distorted_priors(
    rot_deg: float, shift: tuple[float, float]
) -> dict[str, PriorPose]:
    """The model as SfM placed it: true geometry turned and moved as a block."""
    pts = np.array([[x, y] for x, y, _ in TRUE.values()])
    c = pts.mean(axis=0)
    phi = math.radians(rot_deg)
    priors: dict[str, PriorPose] = {}
    for scene, (x, y, h) in TRUE.items():
        rx, ry = x - c[0], y - c[1]
        px = c[0] + rx * math.cos(phi) + ry * math.sin(phi) + shift[0]
        py = c[1] - rx * math.sin(phi) + ry * math.cos(phi) + shift[1]
        priors[scene] = PriorPose(scene, px, py, (h + rot_deg) % 360.0, "m0", "sfm")
    return priors


def _survey(
    extra: dict[str, list[Sighting]] | None = None,
    lms: dict[str, Landmark] | None = None,
) -> Survey:
    landmarks = {
        name: Landmark(name, x, y, 0.5, "xy") for name, (x, y) in CORNERS.items()
    }
    scenes = {
        scene: SceneNotes(
            scene=scene,
            free=False,
            init=None,
            prior_sigma_m=None,
            prior_sigma_deg=None,
            sightings=[
                Sighting(name, _ath(pose, CORNERS[name]), 0.2, True) for name in CORNERS
            ],
        )
        for scene, pose in TRUE.items()
    }
    for scene, sightings in (extra or {}).items():
        notes = scenes[scene]
        scenes[scene] = SceneNotes(
            scene, notes.free, notes.init, None, None, notes.sightings + sightings
        )
    return Survey(tripod_m=1.6, landmarks={**landmarks, **(lms or {})}, scenes=scenes)


def test_solver_recovers_a_turned_and_shifted_model() -> None:
    solution = solve_survey(_distorted_priors(6.0, (4.0, -3.0)), [], _survey())
    assert solution.success, solution.message
    for scene, (x, y, h) in TRUE.items():
        est = solution.poses[scene]
        assert math.hypot(est.x - x, est.y - y) < 0.15, f"{scene}: {est}"
        assert abs((est.heading_deg - h + 180) % 360 - 180) < 0.2, f"{scene}: {est}"
    # The turn is shared between the model and its scenes' elastic headings.
    assert solution.models["m0"].rotation_deg == pytest.approx(-6.0, abs=1.0)


def test_solver_shrugs_off_one_wrong_sighting() -> None:
    wrong = Sighting("A#1", (_ath(TRUE["s1"], CORNERS["A#1"]) + 25.0) % 360, 0.2, True)
    solution = solve_survey(
        _distorted_priors(6.0, (4.0, -3.0)), [], _survey({"s1": [wrong]})
    )
    est = solution.poses["s1"]
    assert math.hypot(est.x - 10.0, est.y - 10.0) < 0.3, f"Got {est}"
    weights = [
        r.weight
        for r in solution.residuals
        if r.scene == "s1" and abs(r.residual_deg) > 10
    ]
    assert weights and max(weights) < 0.01, f"Outlier weights {weights}"


def test_free_scene_moves_to_where_its_sightings_meet() -> None:
    priors = _distorted_priors(0.0, (0.0, 0.0))
    priors["s3"] = PriorPose("s3", 22.0, 28.0, 60.0, None, "manual")
    solution = solve_survey(priors, [], _survey())
    est = solution.poses["s3"]
    assert est.free
    assert math.hypot(est.x - 30.0, est.y - 20.0) < 0.15, f"Got {est}"
    assert est.shift_m == pytest.approx(math.hypot(8.0, 8.0), abs=0.2)


def test_free_landmark_is_triangulated() -> None:
    shop = (33.0, 34.0)
    lms = {"shop": Landmark("shop", 20.0, 20.0, None, "xy")}
    extra = {
        s: [Sighting("shop", _ath(TRUE[s], shop), 0.2, True)]
        for s in ("s1", "s3", "s4")
    }
    solution = solve_survey(
        _distorted_priors(0.0, (0.0, 0.0)), [], _survey(extra, lms=lms)
    )
    est = solution.landmarks["shop"]
    assert est.free
    assert math.hypot(est.x - shop[0], est.y - shop[1]) < 0.2, f"Got {est}"
    assert est.sigma_x < 0.5 and est.sigma_y < 0.5


def test_uncertainty_shrinks_with_evidence() -> None:
    few = _survey()
    few.scenes["s5"] = SceneNotes(
        "s5", True, None, 10.0, 30.0, few.scenes["s5"].sightings[:2]
    )
    many = _survey()
    many.scenes["s5"] = SceneNotes(
        "s5", True, None, 10.0, 30.0, many.scenes["s5"].sightings
    )
    priors = _distorted_priors(0.0, (0.0, 0.0))
    sigma_few = solve_survey(priors, [], few).poses["s5"]
    sigma_many = solve_survey(priors, [], many).poses["s5"]
    assert sigma_many.ellipse[0] < sigma_few.ellipse[0]
    assert sigma_many.ellipse[0] > 0


def test_tour_links_pull_a_free_scene_weakly() -> None:
    priors = _distorted_priors(0.0, (0.0, 0.0))
    priors["s6"] = PriorPose("s6", 12.0, 20.0, 90.0, None, "interpolated")
    # s6 truly at (20, 20) facing east: arrows to s1 and s3 and back.
    truth = (20.0, 20.0, 90.0)
    links = [
        TourLink("s6", "s1", _ath(truth, TRUE["s1"][:2])),
        TourLink("s6", "s3", _ath(truth, TRUE["s3"][:2])),
        TourLink("s6", "s4", _ath(truth, TRUE["s4"][:2])),
        TourLink("s1", "s6", _ath(TRUE["s1"], truth[:2])),
        TourLink("s3", "s6", _ath(TRUE["s3"], truth[:2])),
    ]
    est = solve_survey(
        priors, links, _survey(), SolveConfig(hotspot_sigma_deg=1.0)
    ).poses["s6"]
    assert math.hypot(est.x - 20.0, est.y - 20.0) < 1.0, f"Got {est}"


def test_holdout_predicts_left_out_sightings() -> None:
    errors = holdout(_distorted_priors(6.0, (4.0, -3.0)), [], _survey(), folds=4)
    assert len(errors) == 20
    # Acceptance in the plan: a held-out sighting is predicted within 1°.
    assert float(np.median(np.abs(errors))) < 1.0


def test_parse_survey_resolves_corners_and_defaults(tmp_path: Path) -> None:
    building = BuildingShape(
        id="way/1",
        name="İstanbul Aydın Üniversitesi A Binası",
        code="A",
        outline=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]]),
        height_m=14.0,
        campus=True,
    )
    path = tmp_path / "survey.toml"
    path.write_text(
        """
tripod_m = 1.7
[landmarks."E.door"]
xy = [1.0, 2.0]
free = true

[scenes.scene_1]
pose = "free"
init = [5.0, 6.0, 370.0]
prior_sigma_m = 4.0
obs = [{ lm = "A#1", ath = 10.0, snapped = true }, { lm = "E.door", ath = 400.0 }]
""",
        encoding="utf-8",
    )
    survey = load_survey([building], path)
    assert survey.tripod_m == 1.7
    assert survey.landmarks["A#1"].source == "way/1#1"
    assert (survey.landmarks["A#1"].x, survey.landmarks["A#1"].y) == (10.0, 0.0)
    assert survey.landmarks["E.door"].sigma_m is None
    notes = survey.scenes["scene_1"]
    assert notes.free and notes.init == (5.0, 6.0, 10.0)
    assert [s.sigma_deg for s in notes.sightings] == [0.4, 1.5]
    assert notes.sightings[1].ath_deg == 40.0


def test_parse_survey_rejects_unknown_corner() -> None:
    with pytest.raises(ValueError, match="Z#0"):
        parse_survey({"scenes": {"s": {"obs": [{"lm": "Z#0", "ath": 1.0}]}}}, [])


def test_notebooks_merge_by_area(tmp_path: Path) -> None:
    folder = tmp_path / "survey"
    folder.mkdir()
    (folder / "a.toml").write_text(
        "[landmarks.door]\nxy = [1.0, 2.0]\nfree = true\n"
        '[scenes.s1]\nobs = [{ lm = "door", ath = 10.0 }]\nnote = "west"\n',
        encoding="utf-8",
    )
    (folder / "b.toml").write_text(
        "[landmarks.door]\nxy = [1.0, 2.0]\nfree = true\n"
        '[scenes.s1]\nobs = [{ lm = "door", ath = 12.0 }]\nnote = "east"\n',
        encoding="utf-8",
    )
    survey = load_survey([], folder)
    notes = survey.scenes["s1"]
    assert [s.ath_deg for s in notes.sightings] == [10.0, 12.0]
    assert notes.note == "west / east"


def test_notebooks_reject_conflicting_landmarks(tmp_path: Path) -> None:
    folder = tmp_path / "survey"
    folder.mkdir()
    (folder / "a.toml").write_text("[landmarks.door]\nxy = [1.0, 2.0]\n", "utf-8")
    (folder / "b.toml").write_text("[landmarks.door]\nxy = [5.0, 2.0]\n", "utf-8")
    with pytest.raises(ValueError, match="door"):
        load_survey([], folder)


def test_free_scene_far_off_is_resected_into_place() -> None:
    priors = _distorted_priors(0.0, (0.0, 0.0))
    # 60 m away and facing the wrong way: the global solve alone would stall.
    priors["s2"] = PriorPose("s2", 80.0, -40.0, 200.0, None, "manual")
    solution = solve_survey(priors, [], _survey())
    est = solution.poses["s2"]
    # The wrong hand prior (sigma 5 m, 80 m away) still tugs a little.
    assert math.hypot(est.x - 20.0, est.y - 15.0) < 0.5, f"Got {est}"


def test_tie_point_seen_head_on_is_dropped_with_a_warning() -> None:
    # s1 (10, 10) and s3 (30, 20) look at a point on the line between them.
    point = (20.0, 15.0)
    lms = {"between": Landmark("between", math.nan, math.nan, None, "tie")}
    extra = {
        s: [Sighting("between", _ath(TRUE[s], point), 0.2, True)] for s in ("s1", "s3")
    }
    solution = solve_survey(
        _distorted_priors(0.0, (0.0, 0.0)), [], _survey(extra, lms=lms)
    )
    assert any("between" in w for w in solution.warnings), solution.warnings
    assert all(r.target != "between" for r in solution.residuals)


def test_reported_uncertainty_has_a_floor() -> None:
    solution = solve_survey(_distorted_priors(0.0, (0.0, 0.0)), [], _survey())
    for est in solution.poses.values():
        assert est.ellipse[1] >= 0.3 - 1e-9, f"{est.scene}: {est.ellipse}"
        assert est.sigma_heading_deg >= 0.5 - 1e-9


def test_stacked_panoramas_do_not_poison_the_covariance() -> None:
    priors = _distorted_priors(0.0, (0.0, 0.0))
    # Two panoramas the old map put on one spot, linked by a tour arrow.
    priors["s6"] = PriorPose("s6", 20.0, 15.0, 0.0, None, "interpolated")
    links = [TourLink("s2", "s6", 10.0), TourLink("s6", "s2", 190.0)]
    solution = solve_survey(priors, links, _survey())
    # s6 has no sightings and no usable arrow: its ellipse is its prior's.
    assert solution.poses["s6"].ellipse[0] > 10.0
    assert solution.poses["s2"].ellipse[0] < 1.0


def test_a_tie_point_never_collapses_onto_its_camera() -> None:
    lms = {"door": Landmark("door", math.nan, math.nan, None, "tie")}
    door = (14.0, 13.0)  # 5 m from s1, seen nearly along s1->s2
    extra = {
        s: [Sighting("door", _ath(TRUE[s], door), 0.2, True)] for s in ("s1", "s2")
    }
    solution = solve_survey(
        _distorted_priors(0.0, (0.0, 0.0)), [], _survey(extra, lms=lms)
    )
    est = solution.landmarks.get("door")
    if est is not None:  # dropped as head-on is also acceptable
        for s in ("s1", "s2"):
            x, y, _ = TRUE[s]
            assert math.hypot(est.x - x, est.y - y) >= 0.9


def test_linked_panoramas_never_collapse_onto_each_other() -> None:
    # Two walk stops with no sightings, 5.75 m apart on the old map, whose
    # tour arrows disagree with that geometry. On one spot the arrows'
    # bearings are undefined and cost nothing: the solve must not go there.
    priors = _distorted_priors(0.0, (0.0, 0.0))
    priors["s6"] = PriorPose("s6", 20.0, 22.0, 0.0, None, "interpolated")
    priors["s7"] = PriorPose("s7", 25.75, 22.0, 0.0, None, "interpolated")
    s6, s7 = (20.0, 22.0, 0.0), (25.75, 22.0, 0.0)
    # Arrows to the anchored scenes pin both headings ...
    links = [
        TourLink(a, t, _ath(pose, TRUE[t][:2]))
        for a, pose in (("s6", s6), ("s7", s7))
        for t in ("s1", "s3", "s4")
    ]
    # ... so arrows saying each lies north of the other can only be met by
    # stacking the two (where a bearing is undefined).
    links += [TourLink("s6", "s7", 0.0), TourLink("s7", "s6", 0.0)]
    solution = solve_survey(priors, links, _survey())
    a, b = solution.poses["s6"], solution.poses["s7"]
    gap = math.hypot(a.x - b.x, a.y - b.y)
    assert gap >= 0.9, f"s6 and s7 collapsed to {gap:.3f} m apart"
    # The anchored scenes keep honest uncertainties (no poisoned covariance).
    assert solution.poses["s1"].ellipse[0] > 0.3, solution.poses["s1"].ellipse
