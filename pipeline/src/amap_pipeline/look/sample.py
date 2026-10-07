"""Colour of a patch of a panorama (facade paint, glass, paving)."""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from amap_pipeline.look.render import ByteImage, Strip, render_strip


@dataclass(frozen=True, slots=True)
class Colour:
    rgb: tuple[int, int, int]
    oklab: tuple[float, float, float]
    spread: float  # median absolute deviation of the patch, 0-255

    @property
    def hex(self) -> str:
        return "#{:02x}{:02x}{:02x}".format(*self.rgb)


def srgb_to_oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """sRGB 0-255 to OKLab (Björn Ottosson's matrices)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    lms = (
        np.array(
            [
                [0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005],
            ]
        )
        @ lin
    )
    root = np.cbrt(lms)
    lab = (
        np.array(
            [
                [0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660],
            ]
        )
        @ root
    )
    return float(lab[0]), float(lab[1]), float(lab[2])


def sample_colour(
    faces: Mapping[str, ByteImage],
    ath_deg: float,
    atv_deg: float,
    *,
    radius_deg: float = 1.0,
    px_per_deg: float = 10.0,
) -> Colour:
    """Median colour of a square patch centred on ``(ath, atv)``."""
    strip = Strip(
        ath_start_deg=ath_deg - radius_deg,
        ath_span_deg=2.0 * radius_deg,
        atv_top_deg=atv_deg - radius_deg,
        atv_bottom_deg=atv_deg + radius_deg,
        px_per_deg=px_per_deg,
    )
    patch = render_strip(faces, strip).reshape(-1, 3).astype(np.float64)
    median = np.median(patch, axis=0)
    spread = float(np.median(np.abs(patch - median)))
    r, g, b = (int(np.rint(v)) for v in median)
    rgb = (r, g, b)
    return Colour(rgb=rgb, oklab=srgb_to_oklab(rgb), spread=spread)
