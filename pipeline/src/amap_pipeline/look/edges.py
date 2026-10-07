"""Snap a rough bearing to the vertical edge next to it.

A level panorama shows every vertical line in the world (a building corner, a
door jamb, a lamp post) as a column of constant ``ath`` in an equirectangular
strip. So the strongest coherent horizontal gradient summed down a column is
the edge; a parabola through the peak gives sub-pixel precision.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

from amap_pipeline.look.render import ByteImage, Strip, render_strip


@dataclass(frozen=True, slots=True)
class Snap:
    ath_deg: float  # snapped bearing (rig ath)
    shift_deg: float  # snapped - rough
    strength: float  # peak response
    contrast: float  # peak / median response in the window; > 3 is a clear edge
    polarity: int  # +1: brighter to the right, -1: darker to the right

    @property
    def clear(self) -> bool:
        return self.contrast >= 3.0


def edge_profile(
    strip_image: ByteImage, *, smooth_px: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Signed coherent column response and its absolute value."""
    grey = strip_image.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    grey = gaussian_filter1d(grey, smooth_px, axis=1)
    grad = np.diff(grey, axis=1)
    # Sum the signed gradient: a true vertical edge keeps its sign down the column,
    # texture and slanted lines cancel out.
    signed = grad.sum(axis=0) / grey.shape[0]
    return signed, np.abs(signed)


def snap_edge(
    faces: Mapping[str, ByteImage],
    ath_deg: float,
    *,
    window_deg: float = 1.5,
    atv_top_deg: float = -25.0,
    atv_bottom_deg: float = 10.0,
    px_per_deg: float = 40.0,
) -> Snap:
    """The strongest vertical edge within ``window_deg`` of ``ath_deg``."""
    margin = window_deg + 1.0
    strip = Strip(
        ath_start_deg=ath_deg - margin,
        ath_span_deg=2.0 * margin,
        atv_top_deg=atv_top_deg,
        atv_bottom_deg=atv_bottom_deg,
        px_per_deg=px_per_deg,
    )
    signed, response = edge_profile(render_strip(faces, strip))
    # Gradient column j lies between pixel columns j and j + 1.
    centres = strip.ath_start_deg + (np.arange(response.size) + 1.0) / px_per_deg
    inside = np.abs(centres - ath_deg) <= window_deg
    candidates = np.flatnonzero(inside)
    peak = int(candidates[np.argmax(response[candidates])])
    offset = 0.0
    if 0 < peak < response.size - 1:
        a, b, c = response[peak - 1], response[peak], response[peak + 1]
        denom = a - 2.0 * b + c
        if denom < 0:
            offset = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    snapped = float(centres[peak] + offset / px_per_deg)
    median = float(np.median(response[inside])) + 1e-6
    return Snap(
        ath_deg=snapped % 360.0,
        shift_deg=snapped - ath_deg,
        strength=float(response[peak]),
        contrast=float(response[peak]) / median,
        polarity=1 if signed[peak] > 0 else -1,
    )
