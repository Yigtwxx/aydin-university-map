"""Shared contracts for the Aydın University Map."""

from amap_contracts.geo import (
    CAMPUS_ORIGIN_LAT,
    CAMPUS_ORIGIN_LNG,
    FLORYA_BBOX,
    METRIC_CRS,
    BBox,
)
from amap_contracts.text import lower_tr, search_key

__all__ = [
    "CAMPUS_ORIGIN_LAT",
    "CAMPUS_ORIGIN_LNG",
    "FLORYA_BBOX",
    "METRIC_CRS",
    "BBox",
    "lower_tr",
    "search_key",
]
