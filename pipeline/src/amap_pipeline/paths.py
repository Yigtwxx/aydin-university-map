"""Default locations of the (gitignored) data directory."""

import os
from pathlib import Path


def data_dir() -> Path:
    """``$AMAP_DATA_DIR`` or ``./data`` relative to the working directory."""
    return Path(os.environ.get("AMAP_DATA_DIR", "data"))


def raw_dump() -> Path:
    return data_dir() / "raw" / "tour_scenes.json"


def derived_dir() -> Path:
    return data_dir() / "derived"


def sets_dir() -> Path:
    return derived_dir() / "sets"


def tiles_dir() -> Path:
    return data_dir() / "tiles"


def recon_dir() -> Path:
    return data_dir() / "recon"
