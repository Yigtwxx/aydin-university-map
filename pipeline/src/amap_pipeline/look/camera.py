"""Angles in a panorama and where they point on the map.

A panorama direction is krpano's ``(ath, atv)``: ``ath`` degrees clockwise
from the front face, ``atv`` degrees below the horizon (negative = up). In
rig coordinates (``recon/cubemap.py``: x right, y down, z forward) that is
``[sin ath cos atv, sin atv, cos ath cos atv]``.

A pose places the rig on the map: local metres east/north/up of the camera
and the compass bearing of the front face, so ``bearing = ath + heading``.
``ath`` is what an observation records: it does not depend on the pose, which
is exactly what the survey measures.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

# The vendor's tripod: camera height above the ground it stands on. The survey
# replaces it with a measured value; until then this is the usual 1.6 m.
DEFAULT_TRIPOD_M = 1.6


@dataclass(frozen=True, slots=True)
class Pose:
    scene: str
    x: float  # local metres east of the campus origin
    y: float  # local metres north
    z: float  # camera height, metres (terrain + tripod)
    heading_deg: float  # compass bearing of the front face (ath 0)
    tripod_m: float = DEFAULT_TRIPOD_M

    @property
    def ground_z(self) -> float:
        """Height of the ground under the camera."""
        return self.z - self.tripod_m


def rig_rays(ath_deg: FloatArray, atv_deg: FloatArray) -> FloatArray:
    """Unit rig directions (N, 3) of krpano angles."""
    ath = np.radians(np.asarray(ath_deg, dtype=np.float64))
    atv = np.radians(np.asarray(atv_deg, dtype=np.float64))
    cos_v = np.cos(atv)
    return np.stack([np.sin(ath) * cos_v, np.sin(atv), np.cos(ath) * cos_v], axis=-1)


def rig_angles(dirs: FloatArray) -> tuple[FloatArray, FloatArray]:
    """krpano ``(ath, atv)`` of rig directions; ath in [0, 360)."""
    d = np.asarray(dirs, dtype=np.float64)
    horizontal = np.hypot(d[..., 0], d[..., 2])
    ath = np.degrees(np.arctan2(d[..., 0], d[..., 2])) % 360.0
    atv = np.degrees(np.arctan2(d[..., 1], horizontal))
    return ath, atv


def ath_to_bearing(pose: Pose, ath_deg: float) -> float:
    return (ath_deg + pose.heading_deg) % 360.0


def bearing_to_ath(pose: Pose, bearing_deg: float) -> float:
    return (bearing_deg - pose.heading_deg) % 360.0


def enu_to_rig(pose: Pose, points: FloatArray) -> FloatArray:
    """Rig-frame vectors (N, 3) from the camera to ENU points (N, 3)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    east = p[:, 0] - pose.x
    north = p[:, 1] - pose.y
    up = p[:, 2] - pose.z
    h = math.radians(pose.heading_deg)
    # Rotate the horizontal step into the rig: the front face looks at heading.
    forward = east * math.sin(h) + north * math.cos(h)
    right = east * math.cos(h) - north * math.sin(h)
    return np.stack([right, -up, forward], axis=1)


def rig_to_enu(pose: Pose, dirs: FloatArray) -> FloatArray:
    """ENU directions (N, 3) of rig directions (no translation)."""
    d = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
    h = math.radians(pose.heading_deg)
    right, down, forward = d[:, 0], d[:, 1], d[:, 2]
    east = forward * math.sin(h) + right * math.cos(h)
    north = forward * math.cos(h) - right * math.sin(h)
    return np.stack([east, north, -down], axis=1)


def enu_to_angles(
    pose: Pose, points: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """``(ath, atv, horizontal distance)`` of ENU points seen from ``pose``."""
    rig = enu_to_rig(pose, points)
    ath, atv = rig_angles(rig)
    return ath, atv, np.hypot(rig[:, 0], rig[:, 2])


def ground_point(
    pose: Pose, ath_deg: float, atv_deg: float, ground_z: float | None = None
) -> tuple[float, float] | None:
    """Where the ray at ``(ath, atv)`` meets level ground; None above the horizon.

    ``ground_z`` defaults to the ground under the camera.
    """
    drop = pose.z - (pose.ground_z if ground_z is None else ground_z)
    if atv_deg <= 0.0 or drop <= 0.0:
        return None
    distance = drop / math.tan(math.radians(atv_deg))
    bearing = math.radians(ath_to_bearing(pose, ath_deg))
    return pose.x + distance * math.sin(bearing), pose.y + distance * math.cos(bearing)
