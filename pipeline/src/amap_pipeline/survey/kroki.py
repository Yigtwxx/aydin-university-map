"""The tour's campus sketch ("Florya Yerleşke Krokisi") as position evidence.

The live tour has an illustrated campus map with a marker per panorama
(``data/raw/kroki_markers.json``). The illustration is a perspective render,
so its ground plane maps to the map's by a homography. Fitted to panoramas
whose positions are measured independently (survey sightings), it places
the panoramas the reconstruction never could: entrances like the
Technocenter's, known only from the tour's links.

The vendor drew the markers by hand on an artistic render, so expect metres
of scatter; the fit's own residuals say how many.
"""

import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Marker:
    scene: str
    u: float  # marker centre, layer pixels from the left
    v: float  # from the top
    kind: str  # outdoor | entrance


def read_markers(path: Path) -> dict[str, list[Marker]]:
    """Markers per view, centred (the layer stores the right/top offsets)."""
    data = json.loads(path.read_text("utf-8"))
    half = float(data.get("marker_px", 20)) / 2.0
    views: dict[str, list[Marker]] = {}
    for name, view in data["views"].items():
        width = float(view["layer_w"])
        views[name] = [
            Marker(
                scene=str(m["scene"]),
                u=width - float(m["right"]) - half,
                v=float(m["top"]) + half,
                kind=str(m["kind"]),
            )
            for m in view["markers"]
        ]
    return views


def _normalise(points: FloatArray) -> tuple[FloatArray, FloatArray]:
    centre = points.mean(axis=0)
    scale = math.sqrt(2.0) / max(
        float(np.linalg.norm(points - centre, axis=1).mean()), 1e-9
    )
    t = np.array(
        [[scale, 0, -scale * centre[0]], [0, scale, -scale * centre[1]], [0, 0, 1]]
    )
    homog = np.column_stack([points, np.ones(len(points))]) @ t.T
    return homog[:, :2], t


def fit_homography(src: FloatArray, dst: FloatArray) -> FloatArray:
    """Normalised DLT: 3x3 H with dst ~ H @ src (needs 4+ point pairs)."""
    if len(src) < 4:
        raise ValueError("a homography needs at least 4 point pairs")
    s, ts = _normalise(np.asarray(src, float))
    d, td = _normalise(np.asarray(dst, float))
    rows = []
    for (u, v), (x, y) in zip(s, d, strict=True):
        rows.append([u, v, 1, 0, 0, 0, -x * u, -x * v, -x])
        rows.append([0, 0, 0, u, v, 1, -y * u, -y * v, -y])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    h = vt[-1].reshape(3, 3)
    h = np.linalg.inv(td) @ h @ ts
    return h / h[2, 2]


def fit_similarity(src: FloatArray, dst: FloatArray) -> FloatArray:
    """Rotation, uniform scale and shift (as a 3x3 matrix) for a plan view.

    A plan's y axis points down the page, so it is mirrored before the fit.
    """
    if len(src) < 2:
        raise ValueError("a similarity needs at least 2 point pairs")
    s = np.asarray(src, float) * np.array([1.0, -1.0])
    d = np.asarray(dst, float)
    ms, md = s.mean(axis=0), d.mean(axis=0)
    a, b = s - ms, d - md
    cov = b.T @ a / len(s)
    u, sig, vt = np.linalg.svd(cov)
    sign = np.diag([1.0, np.sign(np.linalg.det(u @ vt))])
    rot = u @ sign @ vt
    scale = float(np.trace(np.diag(sig) @ sign)) / max(
        float((a * a).sum() / len(s)), 1e-12
    )
    t = md - scale * rot @ ms
    m = np.eye(3)
    m[:2, :2] = scale * rot @ np.diag([1.0, -1.0])
    m[:2, 2] = t
    return m


def apply(h: FloatArray, points: FloatArray) -> FloatArray:
    p = np.column_stack([np.asarray(points, float), np.ones(len(points))]) @ h.T
    return p[:, :2] / p[:, 2:3]


@dataclass(frozen=True, slots=True)
class KrokiFit:
    h: FloatArray
    inliers: list[str]
    residuals: dict[str, float]  # metres, every scene with a known position
    scatter_m: float  # median inlier residual: the sketch's own precision


def ransac(
    markers: Sequence[Marker],
    known: Mapping[str, tuple[float, float]],
    *,
    plan: bool = False,
    threshold_m: float = 5.0,
    rounds: int = 2000,
    seed: int = 0,
) -> KrokiFit:
    """Robust sketch->map fit from markers whose positions are known.

    ``plan``: a top view, fitted with a similarity (2+ scenes); otherwise a
    perspective render, fitted with a homography (4+ scenes).
    """
    fit = fit_similarity if plan else fit_homography
    need = 2 if plan else 4
    # One marker per scene: a scene drawn twice must not count twice.
    first: dict[str, Marker] = {}
    for m in markers:
        if m.scene in known:
            first.setdefault(m.scene, m)
    pairs = [(m, known[m.scene]) for m in first.values()]
    if len(pairs) < need:
        raise ValueError(f"only {len(pairs)} scenes with known positions; need {need}")
    src = np.array([[m.u, m.v] for m, _ in pairs])
    dst = np.array([p for _, p in pairs], float)
    rng = random.Random(seed)
    best: tuple[int, float, FloatArray] | None = None
    for _ in range(rounds):
        pick = rng.sample(range(len(pairs)), need)
        try:
            h = fit(src[pick], dst[pick])
        except (ValueError, np.linalg.LinAlgError):
            continue
        err = np.linalg.norm(apply(h, src) - dst, axis=1)
        count = int((err < threshold_m).sum())
        score = float(np.median(err))
        if best is None or count > best[0] or (count == best[0] and score < best[1]):
            best = (count, score, h)
    assert best is not None
    err = np.linalg.norm(apply(best[2], src) - dst, axis=1)
    inl = err < threshold_m
    h = fit(src[inl], dst[inl]) if inl.sum() >= need else best[2]
    err = np.linalg.norm(apply(h, src) - dst, axis=1)
    inl = err < threshold_m
    return KrokiFit(
        h=h,
        inliers=[m.scene for (m, _), ok in zip(pairs, inl, strict=True) if ok],
        residuals={
            m.scene: round(float(e), 2) for (m, _), e in zip(pairs, err, strict=True)
        },
        scatter_m=round(float(np.median(err[inl])) if inl.any() else math.nan, 2),
    )


def place(fit: KrokiFit, markers: Sequence[Marker]) -> dict[str, tuple[float, float]]:
    """Map positions of every marker (mean over a scene's markers)."""
    out: dict[str, list[FloatArray]] = {}
    for m, xy in zip(
        markers, apply(fit.h, np.array([[m.u, m.v] for m in markers])), strict=True
    ):
        out.setdefault(m.scene, []).append(xy)
    return {
        s: (
            round(float(np.mean([p[0] for p in v])), 2),
            round(float(np.mean([p[1] for p in v])), 2),
        )
        for s, v in out.items()
    }
