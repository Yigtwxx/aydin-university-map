"""Compass angles: bearings clockwise from north, residuals folded to ±180°."""

import math
from collections.abc import Iterable


def wrap180(angle_deg: float) -> float:
    """``angle_deg`` folded into [-180, 180)."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def compass_bearing(dx: float, dy: float) -> float:
    """Bearing in [0, 360) of a step ``dx`` east, ``dy`` north."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def circular_mean(angles_deg: Iterable[float]) -> float:
    """Mean direction folded into [-180, 180); 0 for no angles."""
    s = c = 0.0
    for angle in angles_deg:
        rad = math.radians(angle)
        s += math.sin(rad)
        c += math.cos(rad)
    if s == 0.0 and c == 0.0:
        return 0.0
    return wrap180(math.degrees(math.atan2(s, c)))
