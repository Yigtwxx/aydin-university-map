"""Street furniture from ``configs/furniture.toml`` to ``data/out/furniture.json``.

The notebook mirrors :mod:`amap_contracts.furniture` (``[[stairs]]``,
``[[ramps]]``, ``[[railings]]``, ``[[items]]``, ``[[seating]]``); each entry
may also carry ``evidence`` (the panoramas and angles it was measured from),
which stays in the notebook::

    [[stairs]]
    id = "square-to-d-lane"
    foot = [-31.0, 1.5]
    top = [-29.5, 6.0]
    width_m = 3.2
    steps = 12
    rise_m = 1.9
    railings = "both"
    evidence = [{ scene = "scene_428547", ath = 15.0 }]
"""

import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amap_contracts.furniture import FurnitureCollection

DEFAULT_FURNITURE = Path(__file__).parents[3] / "configs" / "furniture.toml"
_GROUPS = ("stairs", "ramps", "railings", "items", "seating")


def read_furniture(path: Path = DEFAULT_FURNITURE) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text("utf-8"))


def build_furniture(notebook: Mapping[str, Any]) -> FurnitureCollection:
    groups = {
        group: [
            {k: v for k, v in entry.items() if k not in ("evidence", "note")}
            for entry in notebook.get(group, [])
        ]
        for group in _GROUPS
    }
    return FurnitureCollection.model_validate(
        {"generated_at": datetime.now(UTC), **groups}
    )
