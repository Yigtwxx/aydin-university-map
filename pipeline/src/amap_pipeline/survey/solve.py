"""One robust adjustment of every panorama pose and every landmark.

Unknowns:

* per SfM model, a 2D similarity about its centroid (rotation, shift,
  log-scale): the model's internal geometry is good, its placement may not be;
* per model panorama, a small elastic offset (x, y, heading), so a model that
  is locally distorted (m0's east side) can still bend where pictures say so;
* per free panorama (placed by hand, interpolated or flagged), its own
  x, y and heading;
* per landmark, its position, pulled towards its prior (an OSM corner) unless
  it is free (a shop front).

Observations are bearings: ``heading + ath`` must point at the landmark (or at
the panorama a tour arrow links to). Priors keep the gauge and the soft facts
(OSM corners, hand placements). Residuals are whitened by their sigma and a
Cauchy loss keeps a wrong OSM corner or a mis-aimed tour arrow from dragging
the rest. The covariance at the solution gives every pose an uncertainty: the
ellipse the report draws, which is the proof.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import OptimizeResult, least_squares
from scipy.sparse import lil_matrix

from amap_pipeline.geo.angles import wrap180
from amap_pipeline.survey.observations import Survey

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.intp]


@dataclass(frozen=True, slots=True)
class PriorPose:
    scene: str
    x: float
    y: float
    heading_deg: float
    model: str | None  # SfM model the pose comes from
    source: str  # sfm | manual | interpolated | survey-init


@dataclass(frozen=True, slots=True)
class TourLink:
    source: str
    target: str
    ath_deg: float


@dataclass(frozen=True, slots=True)
class SolveConfig:
    hotspot_sigma_deg: float = 5.0
    max_link_m: float = 60.0
    min_link_m: float = 2.0
    # The georeference already fits each model to the footprints (ICP RMS about
    # 1 m), so a model moves as a block only when sightings insist; tour arrows
    # are too loosely aimed to turn one on their own.
    model_rotation_sigma_deg: float = 3.0
    model_shift_sigma_m: float = 5.0
    model_log_scale_sigma: float = 0.05
    elastic_sigma_m: float = 1.0
    elastic_heading_sigma_deg: float = 2.0
    manual_sigma_m: float = 5.0  # hand placements become soft priors
    manual_sigma_deg: float = 20.0
    free_sigma_m: float = 30.0  # free panoramas without a stated prior
    free_sigma_deg: float = 90.0
    loss: str = "cauchy"  # landmark sightings: careful, keep some pull
    # Tour arrows: some point the opposite way (a flipped pose or a teleport);
    # a bounded loss caps what any one of them can cost.
    hotspot_loss: str = "geman_mcclure"
    f_scale: float = 2.0  # whitened residuals beyond ~2 sigma lose weight
    # Floors added to the reported uncertainty: what no sighting can see
    # (the lens's nodal point, the corner's true position on the wall).
    pose_floor_m: float = 0.3
    heading_floor_deg: float = 0.5
    landmark_floor_m: float = 0.3
    # A tie point whose rays cross at less than this is placed along the
    # baseline only by chance (two panoramas facing each other).
    min_tie_angle_deg: float = 12.0
    # A sighted point stands at least this far from the camera that sees it;
    # without it a tie with two rays can collapse onto a camera (zero-length
    # ray, zero residual).
    min_range_m: float = 1.0


@dataclass(slots=True)
class _Layout:
    scenes: list[str]
    models: list[str]
    landmarks: list[str]
    model_of: IntArray  # per scene: model index or -1 (free)
    p0: FloatArray  # (S, 2) prior positions
    h0: FloatArray  # (S,) prior headings
    centroid: FloatArray  # (M, 2)
    model_off: int = 0
    elastic_off: IntArray = field(default_factory=lambda: np.zeros(0, np.intp))
    free_off: IntArray = field(default_factory=lambda: np.zeros(0, np.intp))
    lm_off: int = 0
    size: int = 0


@dataclass(frozen=True, slots=True)
class Bearing:
    scene: str
    target: str  # landmark name or scene id
    target_is_scene: bool
    ath_deg: float
    sigma_deg: float
    kind: str  # landmark | hotspot


@dataclass(frozen=True, slots=True)
class PoseEstimate:
    scene: str
    x: float
    y: float
    heading_deg: float
    sigma_x: float
    sigma_y: float
    sigma_heading_deg: float
    ellipse: tuple[
        float, float, float
    ]  # semi-major, semi-minor (1 sigma, m), azimuth deg
    shift_m: float  # distance from the prior position
    turn_deg: float  # heading change from the prior
    model: str | None
    free: bool


@dataclass(frozen=True, slots=True)
class LandmarkEstimate:
    name: str
    x: float
    y: float
    sigma_x: float
    sigma_y: float
    shift_m: float | None  # None for tie points (no prior)
    prior: tuple[float, float] | None
    free: bool
    source: str
    sightings: int = 0  # 0: dropped or never seen; its position is a guess


@dataclass(frozen=True, slots=True)
class Residual:
    scene: str
    target: str
    kind: str
    ath_deg: float
    residual_deg: float
    sigma_deg: float
    weight: float  # robust weight at the solution, 1 = fully trusted


@dataclass(frozen=True, slots=True)
class ModelEstimate:
    model: str
    rotation_deg: float
    shift_m: tuple[float, float]
    scale: float
    scenes: int


@dataclass(frozen=True, slots=True)
class Solution:
    poses: dict[str, PoseEstimate]
    landmarks: dict[str, LandmarkEstimate]
    models: dict[str, ModelEstimate]
    residuals: list[Residual]
    cost: float
    success: bool
    message: str
    warnings: list[str] = field(default_factory=list[str])


class Problem:
    """The adjustment for one set of priors, links and survey notes."""

    def __init__(
        self,
        priors: Mapping[str, PriorPose],
        links: Sequence[TourLink],
        survey: Survey,
        config: SolveConfig | None = None,
    ) -> None:
        self.config = config or SolveConfig()
        self.survey = survey
        self.priors = dict(priors)
        for scene, notes in survey.scenes.items():
            if notes.init is not None:
                x, y, h = notes.init
                old = self.priors.get(scene)
                self.priors[scene] = PriorPose(
                    scene, x, y, h, old.model if old else None, "survey-init"
                )
            elif scene not in self.priors and notes.sightings:
                raise ValueError(f"{scene}: no pose to start from; give init")
        self.warnings: list[str] = []
        self.layout = self._layout()
        self.bearings = self._bearings(links)
        self._index = {s: i for i, s in enumerate(self.layout.scenes)}
        self._lm_index = {n: i for i, n in enumerate(self.layout.landmarks)}
        # Bootstrapping may drop weak tie points from the bearings, so it runs
        # before anything reads them.
        self._start: FloatArray = self._bootstrap(self._from_priors())

    # --- layout ---------------------------------------------------------------

    def _is_free(self, p: PriorPose) -> bool:
        notes = self.survey.scenes.get(p.scene)
        if notes is not None and notes.free:
            return True
        return p.model is None or p.source != "sfm"

    def _layout(self) -> _Layout:
        scenes = sorted(self.priors)
        free = [self._is_free(self.priors[s]) for s in scenes]
        models = sorted(
            {
                str(self.priors[s].model)
                for s, f in zip(scenes, free, strict=True)
                if not f
            }
        )
        m_index = {m: i for i, m in enumerate(models)}
        model_of = np.array(
            [
                -1 if f else m_index[str(self.priors[s].model)]
                for s, f in zip(scenes, free, strict=True)
            ],
            dtype=np.intp,
        )
        p0 = np.array([[self.priors[s].x, self.priors[s].y] for s in scenes], float)
        p0 = p0.reshape(-1, 2)
        h0 = np.array([self.priors[s].heading_deg for s in scenes], dtype=float)
        centroid = np.array(
            [p0[model_of == i].mean(axis=0) for i in range(len(models))], float
        ).reshape(-1, 2)
        layout = _Layout(scenes, models, [], model_of, p0, h0, centroid)
        offset = 4 * len(models)
        elastic = np.full(len(scenes), -1, dtype=np.intp)
        free_off = np.full(len(scenes), -1, dtype=np.intp)
        for i in range(len(scenes)):
            if model_of[i] >= 0:
                elastic[i] = offset
            else:
                free_off[i] = offset
            offset += 3
        layout.elastic_off = elastic
        layout.free_off = free_off
        layout.landmarks = sorted(self.survey.landmarks)
        layout.lm_off = offset
        layout.size = offset + 2 * len(layout.landmarks)
        return layout

    def _bearings(self, links: Sequence[TourLink]) -> list[Bearing]:
        out: list[Bearing] = []
        for scene, notes in sorted(self.survey.scenes.items()):
            for s in notes.sightings:
                out.append(
                    Bearing(
                        scene, s.landmark, False, s.ath_deg, s.sigma_deg, "landmark"
                    )
                )
        known = set(self.layout.scenes)
        for link in links:
            if link.source not in known or link.target not in known:
                continue
            a, b = self.priors[link.source], self.priors[link.target]
            length = math.hypot(b.x - a.x, b.y - a.y)
            # Teleports, and panoramas the old map stacked on one spot (their
            # bearing is undefined and its derivative explodes).
            if not self.config.min_link_m <= length <= self.config.max_link_m:
                continue
            out.append(
                Bearing(
                    link.source,
                    link.target,
                    True,
                    link.ath_deg % 360.0,
                    self.config.hotspot_sigma_deg,
                    "hotspot",
                )
            )
        return out

    # --- model ----------------------------------------------------------------

    def initial(self) -> FloatArray:
        """Start: priors, then resected free panoramas and triangulated ties."""
        return self._start.copy()

    def _from_priors(self) -> FloatArray:
        x0 = np.zeros(self.layout.size)
        lay = self.layout
        for i in range(len(lay.scenes)):
            off = lay.free_off[i]
            if off >= 0:
                x0[off : off + 2] = lay.p0[i]
                x0[off + 2] = lay.h0[i]
        for j, name in enumerate(lay.landmarks):
            lm = self.survey.landmarks[name]
            start = (lm.x, lm.y)
            if lm.sigma_m is None:
                start = self._intersect(name) or self._along_ray(name) or start
            if not all(math.isfinite(v) for v in start):
                raise ValueError(f"tie point {name}: nobody sights it")
            x0[lay.lm_off + 2 * j : lay.lm_off + 2 * j + 2] = start
        return x0

    def _bootstrap(self, x0: FloatArray) -> FloatArray:
        """Resect free panoramas from landmarks with known positions, then
        triangulate the tie points they see; repeat while it helps.

        A free panorama whose sightings all lie on one side has a cost valley
        far from its true place; starting the global solve from a resection
        (multi-start) keeps it out of that valley.
        """
        lay = self.layout
        known: dict[str, tuple[float, float]] = {
            name: (lm.x, lm.y)
            for name, lm in self.survey.landmarks.items()
            if lm.sigma_m is not None and math.isfinite(lm.x)
        }
        sightings: dict[str, list[Bearing]] = {}
        for b in self.bearings:
            if b.kind == "landmark":
                sightings.setdefault(b.scene, []).append(b)
        posed: set[str] = {s for i, s in enumerate(lay.scenes) if lay.model_of[i] >= 0}
        for _ in range(4):
            progress = False
            for scene, seen in sorted(sightings.items()):
                i = self._index.get(scene)
                if i is None or lay.model_of[i] >= 0 or scene in posed:
                    continue
                usable = [b for b in seen if b.target in known]
                if len(usable) < 3:
                    continue
                off = int(lay.free_off[i])
                pose = _resect(usable, known, (x0[off], x0[off + 1], x0[off + 2]))
                if pose is not None:
                    x0[off : off + 3] = pose
                    posed.add(scene)
                    progress = True
            xy, heading = self._state_at(x0)
            for name, lm in self.survey.landmarks.items():
                if name in known or lm.sigma_m is not None:
                    continue
                rays = [
                    (
                        xy[self._index[b.scene]],
                        heading[self._index[b.scene]] + b.ath_deg,
                    )
                    for b in self.bearings
                    if b.kind == "landmark" and b.target == name and b.scene in posed
                ]
                point = _triangulate(rays, self.config.min_tie_angle_deg)
                if point is not None:
                    known[name] = point
                    j = self._lm_index[name]
                    x0[lay.lm_off + 2 * j : lay.lm_off + 2 * j + 2] = point
                    progress = True
            if not progress:
                break
        self._drop_weak_ties(x0)
        return x0

    def _state_at(self, params: FloatArray) -> tuple[FloatArray, FloatArray]:
        return self.scene_state(params)

    def _drop_weak_ties(self, x0: FloatArray) -> None:
        """Tie points whose rays never cross at a usable angle are dropped."""
        xy, heading = self._state_at(x0)
        weak: set[str] = set()
        for name, lm in self.survey.landmarks.items():
            if lm.sigma_m is not None:
                continue
            directions = [
                heading[self._index[b.scene]] + b.ath_deg
                for b in self.bearings
                if b.kind == "landmark" and b.target == name
            ]
            best = max(
                (
                    min(abs(wrap180(a - b)), 180.0 - abs(wrap180(a - b)))
                    for k, a in enumerate(directions)
                    for b in directions[k + 1 :]
                ),
                default=0.0,
            )
            if best < self.config.min_tie_angle_deg:
                weak.add(name)
                self.warnings.append(
                    f"tie point {name}: rays cross at {best:.0f}° at most; dropped"
                )
        if weak:
            self.bearings = [b for b in self.bearings if b.target not in weak]
        _ = xy

    def _along_ray(
        self, landmark: str, distance_m: float = 10.0
    ) -> tuple[float, float] | None:
        """A guess on the first sighting ray, for ties the rays can't place."""
        for b in self.bearings:
            if b.kind == "landmark" and b.target == landmark:
                p = self.priors[b.scene]
                rad = math.radians(p.heading_deg + b.ath_deg)
                return p.x + distance_m * math.sin(rad), p.y + distance_m * math.cos(
                    rad
                )
        return None

    def _intersect(self, landmark: str) -> tuple[float, float] | None:
        """Least-squares meeting point of the sighting rays from the prior poses."""
        normal = np.zeros((2, 2))
        rhs = np.zeros(2)
        rays = 0
        for b in self.bearings:
            if b.target_is_scene or b.target != landmark:
                continue
            p = self.priors[b.scene]
            bearing = math.radians(p.heading_deg + b.ath_deg)
            d = np.array([math.sin(bearing), math.cos(bearing)])
            proj = np.eye(2) - np.outer(d, d)
            normal += proj
            rhs += proj @ np.array([p.x, p.y])
            rays += 1
        if rays < 2 or abs(np.linalg.det(normal)) < 1e-6:
            return None
        x, y = np.linalg.solve(normal, rhs)
        return float(x), float(y)

    def scene_state(self, params: FloatArray) -> tuple[FloatArray, FloatArray]:
        """Positions (S, 2) and headings (S,) of every panorama."""
        lay = self.layout
        xy = np.empty_like(lay.p0)
        heading = np.empty_like(lay.h0)
        for m in range(len(lay.models)):
            mask = lay.model_of == m
            if not mask.any():
                continue
            rot, tx, ty, log_s = params[4 * m : 4 * m + 4]
            phi = math.radians(rot)
            scale = math.exp(log_s)
            c, s = math.cos(phi), math.sin(phi)
            rel = lay.p0[mask] - lay.centroid[m]
            # Clockwise by phi (compass sense): bearings grow by rot.
            rx = rel[:, 0] * c + rel[:, 1] * s
            ry = -rel[:, 0] * s + rel[:, 1] * c
            offs = lay.elastic_off[mask]
            ex = params[offs]
            ey = params[offs + 1]
            eh = params[offs + 2]
            xy[mask, 0] = lay.centroid[m, 0] + scale * rx + tx + ex
            xy[mask, 1] = lay.centroid[m, 1] + scale * ry + ty + ey
            heading[mask] = lay.h0[mask] + rot + eh
        free = lay.model_of < 0
        if free.any():
            offs = lay.free_off[free]
            xy[free, 0] = params[offs]
            xy[free, 1] = params[offs + 1]
            heading[free] = params[offs + 2]
        return xy, heading

    def landmark_xy(self, params: FloatArray) -> FloatArray:
        lay = self.layout
        return params[lay.lm_off : lay.lm_off + 2 * len(lay.landmarks)].reshape(-1, 2)

    def _bearing_arrays(
        self, bearings: Sequence[Bearing]
    ) -> tuple[IntArray, IntArray, NDArray[np.bool_], FloatArray, FloatArray]:
        src = np.array([self._index[b.scene] for b in bearings], dtype=np.intp)
        tgt = np.array(
            [
                self._index[b.target] if b.target_is_scene else self._lm_index[b.target]
                for b in bearings
            ],
            dtype=np.intp,
        )
        is_scene = np.array([b.target_is_scene for b in bearings], dtype=bool)
        ath = np.array([b.ath_deg for b in bearings], dtype=float)
        sigma = np.array([b.sigma_deg for b in bearings], dtype=float)
        return src, tgt, is_scene, ath, sigma

    def bearing_residuals(
        self, params: FloatArray, bearings: Sequence[Bearing]
    ) -> FloatArray:
        """Unwhitened residuals in degrees: heading + ath - bearing to target."""
        if not bearings:
            return np.zeros(0)
        xy, heading = self.scene_state(params)
        lms = self.landmark_xy(params)
        src, tgt, is_scene, ath, _ = self._bearing_arrays(bearings)
        target = np.empty((len(bearings), 2))
        target[is_scene] = xy[tgt[is_scene]]
        target[~is_scene] = lms[tgt[~is_scene]]
        d = target - xy[src]
        bearing = np.degrees(np.arctan2(d[:, 0], d[:, 1]))
        return (heading[src] + ath - bearing + 180.0) % 360.0 - 180.0

    def range_penalty(
        self, params: FloatArray, bearings: Sequence[Bearing]
    ) -> FloatArray:
        """One row per landmark sighting: zero unless the point is closer to
        its camera than ``min_range_m``."""
        rows = [b for b in bearings if not b.target_is_scene]
        if not rows:
            return np.zeros(0)
        xy, _ = self.scene_state(params)
        lms = self.landmark_xy(params)
        src = np.array([self._index[b.scene] for b in rows], dtype=np.intp)
        tgt = np.array([self._lm_index[b.target] for b in rows], dtype=np.intp)
        dist = np.linalg.norm(lms[tgt] - xy[src], axis=1)
        return np.maximum(0.0, self.config.min_range_m - dist) / 0.1

    def residuals(
        self,
        params: FloatArray,
        bearings: Sequence[Bearing],
        f_scale: float | None = None,
    ) -> FloatArray:
        """Whitened residuals; only the sightings go through the robust loss.

        Priors stay quadratic: a robust prior would give up exactly when the
        observations pull hardest, letting a model drift on a few bad arrows.
        """
        cfg, lay = self.config, self.layout
        parts: list[FloatArray] = []
        if bearings:
            sigma = np.array([b.sigma_deg for b in bearings])
            whitened = self.bearing_residuals(params, bearings) / sigma
            f = f_scale or cfg.f_scale
            arrows = np.array([b.kind == "hotspot" for b in bearings])
            out = robust(whitened, cfg.loss, f)
            out[arrows] = robust(whitened[arrows], cfg.hotspot_loss, f)
            parts.append(out)
            parts.append(self.range_penalty(params, bearings))
        for m in range(len(lay.models)):
            rot, tx, ty, log_s = params[4 * m : 4 * m + 4]
            parts.append(
                np.array(
                    [
                        rot / cfg.model_rotation_sigma_deg,
                        tx / cfg.model_shift_sigma_m,
                        ty / cfg.model_shift_sigma_m,
                        log_s / cfg.model_log_scale_sigma,
                    ]
                )
            )
        model_scenes = lay.model_of >= 0
        if model_scenes.any():
            offs = lay.elastic_off[model_scenes]
            parts.append(params[offs] / cfg.elastic_sigma_m)
            parts.append(params[offs + 1] / cfg.elastic_sigma_m)
            parts.append(params[offs + 2] / cfg.elastic_heading_sigma_deg)
        for i in np.flatnonzero(lay.model_of < 0):
            sm, sd = self._free_sigmas(lay.scenes[i])
            off = lay.free_off[i]
            parts.append(
                np.array(
                    [
                        (params[off] - lay.p0[i, 0]) / sm,
                        (params[off + 1] - lay.p0[i, 1]) / sm,
                        wrap180(params[off + 2] - lay.h0[i]) / sd,
                    ]
                )
            )
        lms = self.landmark_xy(params)
        for j, name in enumerate(lay.landmarks):
            lm = self.survey.landmarks[name]
            if lm.sigma_m is not None:
                # OSM corners can be wrong: finding those is half the point.
                offset = (lms[j] - (lm.x, lm.y)) / lm.sigma_m
                parts.append(robust(offset, cfg.loss, f_scale or cfg.f_scale))
        return np.concatenate(parts) if parts else np.zeros(0)

    def _free_sigmas(self, scene: str) -> tuple[float, float]:
        cfg = self.config
        notes = self.survey.scenes.get(scene)
        prior = self.priors[scene]
        if prior.source == "manual":
            sm, sd = cfg.manual_sigma_m, cfg.manual_sigma_deg
        else:
            sm, sd = cfg.free_sigma_m, cfg.free_sigma_deg
        if notes is not None:
            sm = notes.prior_sigma_m or sm
            sd = notes.prior_sigma_deg or sd
        return sm, sd

    def sparsity(self, bearings: Sequence[Bearing]) -> lil_matrix:
        lay = self.layout
        rows = len(self.residuals(self.initial(), bearings))
        pattern = lil_matrix((rows, lay.size), dtype=np.int8)

        def scene_cols(i: int) -> list[int]:
            m = int(lay.model_of[i])
            if m >= 0:
                off = int(lay.elastic_off[i])
                return [*range(4 * m, 4 * m + 4), off, off + 1, off + 2]
            off = int(lay.free_off[i])
            return [off, off + 1, off + 2]

        r = 0
        for b in bearings:
            cols = scene_cols(self._index[b.scene])
            if b.target_is_scene:
                cols += scene_cols(self._index[b.target])
            else:
                j = self._lm_index[b.target]
                cols += [lay.lm_off + 2 * j, lay.lm_off + 2 * j + 1]
            for c in cols:
                pattern[r, c] = 1
            r += 1
        for b in bearings:
            if b.target_is_scene:
                continue
            j = self._lm_index[b.target]
            for c in [
                *scene_cols(self._index[b.scene]),
                lay.lm_off + 2 * j,
                lay.lm_off + 2 * j + 1,
            ]:
                pattern[r, c] = 1
            r += 1
        for m in range(len(lay.models)):
            for k in range(4):
                pattern[r, 4 * m + k] = 1
                r += 1
        model_scenes = np.flatnonzero(lay.model_of >= 0)
        for k in range(3):
            for i in model_scenes:
                pattern[r, int(lay.elastic_off[i]) + k] = 1
                r += 1
        for i in np.flatnonzero(lay.model_of < 0):
            for k in range(3):
                pattern[r, int(lay.free_off[i]) + k] = 1
                r += 1
        for j, name in enumerate(lay.landmarks):
            if self.survey.landmarks[name].sigma_m is not None:
                pattern[r, lay.lm_off + 2 * j] = 1
                pattern[r + 1, lay.lm_off + 2 * j + 1] = 1
                r += 2
        return pattern

    # --- solving ----------------------------------------------------------------

    def solve(
        self, bearings: Sequence[Bearing] | None = None
    ) -> tuple[FloatArray, OptimizeResult]:
        use = self.bearings if bearings is None else bearings
        sparsity = self.sparsity(use)
        params = self.initial()
        # Graduated non-convexity: a wide loss first, so far-off starts are not
        # written off as outliers, then the configured one.
        base = self.config.f_scale
        result = None
        for f_scale in (100.0 * base, 10.0 * base, base):
            result = least_squares(
                self.residuals,
                params,
                args=(use, f_scale),
                jac_sparsity=sparsity,
                x_scale="jac",
                method="trf",
                max_nfev=8000,
            )
            params = np.asarray(result.x, dtype=float)
        assert result is not None
        return params, result

    def covariance(self, params: FloatArray, result: OptimizeResult) -> FloatArray:
        # The Jacobian of the robustified residuals already carries each
        # sighting's weight: Gauss-Newton on the robust cost.
        jac = result.jac
        dense = jac.toarray() if hasattr(jac, "toarray") else np.asarray(jac)
        normal = dense.T @ dense
        # Eigen-inverse with a floor: a direction the data barely constrain
        # gets a large variance (pinv would report zero for it).
        values, vectors = np.linalg.eigh((normal + normal.T) / 2.0)
        floor = max(float(values.max()), 1.0) * 1e-12
        cov = (vectors / np.maximum(values, floor)) @ vectors.T
        # Scale by the reduced chi-square when the fit is worse than the
        # sigmas claim (never shrink below them).
        m, n = dense.shape
        if m > n:
            factor = 2.0 * float(result.cost) / (m - n)
            cov *= max(1.0, factor)
        return cov

    def state_jacobian(self, params: FloatArray) -> FloatArray:
        """d(x, y, heading of every scene) / d(params), by central differences."""
        lay = self.layout
        n_s = len(lay.scenes)
        jac = np.zeros((3 * n_s, lay.size))
        step = 1e-4
        for k in range(lay.lm_off):
            plus, minus = params.copy(), params.copy()
            plus[k] += step
            minus[k] -= step
            xp, hp = self.scene_state(plus)
            xm, hm = self.scene_state(minus)
            jac[0::3, k] = (xp[:, 0] - xm[:, 0]) / (2 * step)
            jac[1::3, k] = (xp[:, 1] - xm[:, 1]) / (2 * step)
            jac[2::3, k] = (hp - hm) / (2 * step)
        return jac


def _resect(
    sightings: Sequence[Bearing],
    known: Mapping[str, tuple[float, float]],
    start: tuple[float, float, float],
    *,
    max_rms_deg: float = 3.0,
) -> tuple[float, float, float] | None:
    """Position and heading from 3+ bearings to known points (multi-start).

    Starts from ``start`` and from a grid around the seen points, each with
    the heading that best fits there; keeps the lowest cost. None when even
    the best start leaves the bearings disagreeing.
    """
    targets = np.array([known[b.target] for b in sightings], float)
    ath = np.array([b.ath_deg for b in sightings], float)
    sigma = np.array([b.sigma_deg for b in sightings], float)

    def residual(p: FloatArray) -> FloatArray:
        d = targets - p[:2]
        bearing = np.degrees(np.arctan2(d[:, 0], d[:, 1]))
        return ((p[2] + ath - bearing + 180.0) % 360.0 - 180.0) / sigma

    def best_heading(x: float, y: float) -> float:
        d = targets - (x, y)
        bearing = np.degrees(np.arctan2(d[:, 0], d[:, 1]))
        diffs = np.radians(bearing - ath)
        return math.degrees(math.atan2(np.sin(diffs).sum(), np.cos(diffs).sum()))

    centre = targets.mean(axis=0)
    starts = [np.array(start, float)]
    for dx in (-30.0, -15.0, 0.0, 15.0, 30.0):
        for dy in (-30.0, -15.0, 0.0, 15.0, 30.0):
            x, y = centre[0] + dx, centre[1] + dy
            starts.append(np.array([x, y, best_heading(x, y)]))
    best: tuple[float, FloatArray] | None = None
    for p0 in starts:
        result = least_squares(residual, p0, loss="soft_l1", f_scale=3.0)
        cost = float(np.sqrt(np.mean((residual(result.x) * sigma) ** 2)))
        if best is None or cost < best[0]:
            best = (cost, np.asarray(result.x, float))
    assert best is not None
    if best[0] > max_rms_deg:
        return None
    x, y, h = best[1]
    return float(x), float(y), float(h % 360.0)


def _triangulate(
    rays: Sequence[tuple[FloatArray, float]], min_angle_deg: float
) -> tuple[float, float] | None:
    """Meeting point of bearing rays; None if no two cross at a usable angle."""
    if len(rays) < 2:
        return None
    angles = [b for _, b in rays]
    widest = max(
        min(abs(wrap180(a - b)), 180.0 - abs(wrap180(a - b)))
        for k, a in enumerate(angles)
        for b in angles[k + 1 :]
    )
    if widest < min_angle_deg:
        return None
    normal = np.zeros((2, 2))
    rhs = np.zeros(2)
    for origin, bearing in rays:
        rad = math.radians(bearing)
        d = np.array([math.sin(rad), math.cos(rad)])
        proj = np.eye(2) - np.outer(d, d)
        normal += proj
        rhs += proj @ np.asarray(origin, float)
    x, y = np.linalg.solve(normal, rhs)
    return float(x), float(y)


def robust(z: FloatArray, loss: str, f_scale: float) -> FloatArray:
    """Residuals whose squares sum to the robust cost of whitened ``z``."""
    if loss == "linear":
        return z
    if loss == "cauchy":
        return np.sign(z) * f_scale * np.sqrt(np.log1p((z / f_scale) ** 2))
    if loss == "geman_mcclure":
        # z² / (1 + z²/f²): quadratic near zero, never more than f².
        return z / np.sqrt(1.0 + (z / f_scale) ** 2)
    raise ValueError(f"unknown loss {loss!r}")


def _ellipse(cov: FloatArray) -> tuple[float, float, float]:
    values, vectors = np.linalg.eigh(cov)
    values = np.clip(values, 0.0, None)
    major = vectors[:, 1]
    azimuth = math.degrees(math.atan2(major[0], major[1])) % 180.0
    return (
        round(math.sqrt(values[1]), 3),
        round(math.sqrt(values[0]), 3),
        round(azimuth, 1),
    )


def solve_survey(
    priors: Mapping[str, PriorPose],
    links: Sequence[TourLink],
    survey: Survey,
    config: SolveConfig | None = None,
) -> Solution:
    problem = Problem(priors, links, survey, config)
    params, result = problem.solve()
    cov = problem.covariance(params, result)
    lay = problem.layout
    xy, heading = problem.scene_state(params)
    g = problem.state_jacobian(params)
    poses: dict[str, PoseEstimate] = {}
    for i, scene in enumerate(lay.scenes):
        rows = g[3 * i : 3 * i + 3]
        c = rows @ cov @ rows.T
        prior = problem.priors[scene]
        floor = problem.config.pose_floor_m**2
        c[0, 0] += floor
        c[1, 1] += floor
        c[2, 2] += problem.config.heading_floor_deg**2
        poses[scene] = PoseEstimate(
            scene=scene,
            x=float(xy[i, 0]),
            y=float(xy[i, 1]),
            heading_deg=float(heading[i] % 360.0),
            sigma_x=float(math.sqrt(max(c[0, 0], 0.0))),
            sigma_y=float(math.sqrt(max(c[1, 1], 0.0))),
            sigma_heading_deg=float(math.sqrt(max(c[2, 2], 0.0))),
            ellipse=_ellipse(c[:2, :2]),
            shift_m=float(math.hypot(xy[i, 0] - prior.x, xy[i, 1] - prior.y)),
            turn_deg=float(wrap180(heading[i] - prior.heading_deg)),
            model=prior.model,
            free=bool(lay.model_of[i] < 0),
        )
    lms = problem.landmark_xy(params)
    lm_floor = problem.config.landmark_floor_m**2
    seen: dict[str, int] = {}
    for b in problem.bearings:
        if not b.target_is_scene:
            seen[b.target] = seen.get(b.target, 0) + 1
    landmarks: dict[str, LandmarkEstimate] = {}
    for j, name in enumerate(lay.landmarks):
        lm = survey.landmarks[name]
        k = lay.lm_off + 2 * j
        landmarks[name] = LandmarkEstimate(
            name=name,
            x=float(lms[j, 0]),
            y=float(lms[j, 1]),
            sigma_x=float(math.sqrt(max(cov[k, k], 0.0) + lm_floor)),
            sigma_y=float(math.sqrt(max(cov[k + 1, k + 1], 0.0) + lm_floor)),
            shift_m=(
                None
                if lm.source == "tie"
                else float(math.hypot(lms[j, 0] - lm.x, lms[j, 1] - lm.y))
            ),
            prior=None if lm.source == "tie" else (lm.x, lm.y),
            free=lm.sigma_m is None,
            source=lm.source,
            sightings=seen.get(name, 0),
        )
    models = {
        m: ModelEstimate(
            model=m,
            rotation_deg=float(params[4 * i]),
            shift_m=(float(params[4 * i + 1]), float(params[4 * i + 2])),
            scale=float(math.exp(params[4 * i + 3])),
            scenes=int((lay.model_of == i).sum()),
        )
        for i, m in enumerate(lay.models)
    }
    raw = problem.bearing_residuals(params, problem.bearings)
    residuals = []
    for b, r in zip(problem.bearings, raw, strict=True):
        z = (r / b.sigma_deg / problem.config.f_scale) ** 2
        residuals.append(
            Residual(
                scene=b.scene,
                target=b.target,
                kind=b.kind,
                ath_deg=b.ath_deg,
                residual_deg=float(r),
                sigma_deg=b.sigma_deg,
                weight=float(1.0 / (1.0 + z)),
            )
        )
    return Solution(
        poses=poses,
        landmarks=landmarks,
        models=models,
        residuals=residuals,
        cost=float(result.cost),
        success=bool(result.success),
        message=str(result.message),
        warnings=list(problem.warnings),
    )


def holdout(
    priors: Mapping[str, PriorPose],
    links: Sequence[TourLink],
    survey: Survey,
    config: SolveConfig | None = None,
    *,
    folds: int = 5,
) -> list[float]:
    """Residuals (degrees) of landmark sightings predicted by solves without them."""
    problem = Problem(priors, links, survey, config)
    sightings = [i for i, b in enumerate(problem.bearings) if b.kind == "landmark"]
    out: list[float] = []
    for k in range(min(folds, len(sightings))):
        held = set(sightings[k::folds])
        kept = [b for i, b in enumerate(problem.bearings) if i not in held]
        params, _ = problem.solve(kept)
        test = [problem.bearings[i] for i in sorted(held)]
        out.extend(float(v) for v in problem.bearing_residuals(params, test))
    return out
