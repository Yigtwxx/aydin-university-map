"""Satellite "earth" textures for the landing fly-in, in local metres.

Three nested, axis-aligned square levels around the campus (:data:`LEVELS`)
are resampled from Web Mercator tile mosaics into the local metric grid of
:class:`LocalProjector` (UTM 35N minus the campus origin; x east, y north).
For every output pixel centre (x, y): local metres -> WGS84 -> global Web
Mercator pixel -> interpolated sample. Row 0 of every image is the north edge,
column 0 the west edge.

Output layout (``data/out/earth/``, published to the asset host, never git)::

    day_L{i}.webp     Sentinel-2 cloudless 2024 (EOX), faithful resampling
    night_L{i}.webp   VIIRS Black Marble; on L1/L2 its light is redistributed
                      onto OSM road lights and the built-up fabric
    height_L{i}.png   Terrarium terrain; sea 0 m, lakes flat, land >= 0.5 m
    water_L{i}.png    R water coverage, G distance to shore (0..1500 m), B 0
    earth.json        manifest: levels, files, height range, attribution

Tiles are cached under ``data/cache/earth/<source>/<z>/<x>/<y>.<ext>`` and
Overpass responses under ``data/osm/``, so re-runs are resumable and offline.
"""

import json
import logging
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any, Self

import numpy as np
from numpy.typing import ArrayLike, NDArray
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG, BBox
from amap_pipeline.geo.osm import USER_AGENT, LocalProjector
from amap_pipeline.geo.region import (
    MINOR_WATER_KINDS,
    classify_faces,
    coastline_faces,
    coastline_lines,
    fetch_coastline_raw,
    fetch_land_raw,
    fetch_roads_raw,
    fetch_water_bodies_raw,
    parse_land,
    parse_water_bodies,
)

log = logging.getLogger(__name__)

FloatArray = NDArray[np.float64]
Float32Array = NDArray[np.float32]
ByteArray = NDArray[np.uint8]

TILE_PX = 256
WEB_MERCATOR_CIRCUMFERENCE_M = 2 * math.pi * 6_378_137.0
SHORE_MAX_M = 1500.0
# Terrarium stores 1/256 m; SRTM-class data is metre-accurate, and rounding to
# 1/8 m makes the PNGs ~40 % smaller.
HEIGHT_STEP_M = 0.125
LAND_MIN_M = 0.5
MAX_WORKERS = 4  # politeness cap for every tile server
MANIFEST_VERSION = 1
CRS_ID = "local-utm35n"
# The coastline frame extends this far past the largest level, so the padded
# grids used for the shore distance still see real land and sea.
COAST_MARGIN_M = 3000.0
# Overpass reserves resources by the declared timeout: a modest one gets a slot
# on a busy server far sooner, and every query here runs in seconds.
OVERPASS_TIMEOUT_S = 90
ROAD_OVERPASS_TIMEOUT_S = 60
OVERPASS_ROUNDS = 6  # patient retries on top of the mirror rotation
OVERPASS_ROUND_WAIT_S = 30.0

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
NATURAL_EARTH_ATTRIBUTION = "Natural Earth (public domain)"


# --- sources --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TileSource:
    """A keyless XYZ tile server (256 px Web Mercator tiles)."""

    name: str  # cache directory
    url: str  # template with {z}, {x}, {y}
    ext: str
    max_zoom: int
    attribution: str
    fill: tuple[int, int, int] = (0, 0, 0)  # RGB for tiles the server lacks

    def tile_url(self, z: int, x: int, y: int) -> str:
        return self.url.format(z=z, x=x, y=y)


EOX_S2 = TileSource(
    name="eox-s2cloudless-2024",
    url=(
        "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/"
        "{z}/{y}/{x}.jpg"
    ),
    ext="jpg",
    max_zoom=17,
    attribution=(
        "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH "
        "(Contains modified Copernicus Sentinel data 2024)"
    ),
)
BLACK_MARBLE = TileSource(
    name="viirs-black-marble-2016",
    url=(
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/"
        "default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png"
    ),
    ext="png",
    max_zoom=8,
    attribution="NASA Earth Observatory / GIBS, VIIRS Black Marble",
)
TERRARIUM = TileSource(
    name="terrarium",
    url="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
    ext="png",
    max_zoom=15,
    attribution=(
        "Terrain Tiles by Mapzen/Tilezen (AWS Open Data): SRTM, GMTED2010 and "
        "3DEP terrain data courtesy of the U.S. Geological Survey; ETOPO1 U.S. "
        "National Oceanic and Atmospheric Administration; EU-DEM produced using "
        "Copernicus data and information funded by the European Union; and others "
        "(https://github.com/tilezen/joerd/blob/master/docs/attribution.md)"
    ),
    fill=(128, 0, 0),  # 0 m
)


# --- levels ---------------------------------------------------------------------------

MAJOR_ROADS = (
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
)
MINOR_ROADS = (
    "tertiary",
    "tertiary_link",
    "residential",
    "unclassified",
    "living_street",
)


@dataclass(frozen=True, slots=True)
class EarthLevel:
    """One nested square of the fly-in, axis-aligned in local metres."""

    id: str
    centre: tuple[float, float]
    size_m: float
    day_px: int  # also the night texture size
    height_px: int
    water_px: int
    day_zoom: int
    terrain_zoom: int
    night_zoom: int
    min_water_m2: float  # smallest inland water body kept
    road_kinds: tuple[str, ...] = ()  # OSM highway values lit at night
    road_query_tiles: int = 1  # Overpass road query split into n x n boxes
    # Night light density of built-up pixels relative to road lights: high where
    # the level has no minor streets (the fabric stands in for them).
    night_fabric: float = 0.12
    height_smooth_px: float = 0.0
    day_quality: int = 82
    night_quality: int = 80

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(west, south, east, north)`` in local metres."""
        cx, cy = self.centre
        half = self.size_m / 2
        return cx - half, cy - half, cx + half, cy + half

    def file(self, layer: str) -> str:
        ext = "webp" if layer in ("day", "night") else "png"
        return f"{layer}_{self.id}.{ext}"


LEVELS: tuple[EarthLevel, ...] = (
    EarthLevel(
        id="L0",
        centre=(12_000.0, 8_000.0),
        size_m=170_000.0,
        day_px=2048,
        height_px=512,
        water_px=2048,
        day_zoom=11,
        terrain_zoom=10,
        night_zoom=8,
        min_water_m2=200_000.0,
        height_smooth_px=1.0,
    ),
    EarthLevel(
        id="L1",
        centre=(10_000.0, 6_000.0),
        size_m=48_000.0,
        day_px=4096,
        height_px=1024,
        water_px=2048,
        day_zoom=13,
        terrain_zoom=12,
        night_zoom=8,
        min_water_m2=200_000.0,
        road_kinds=MAJOR_ROADS,
        road_query_tiles=4,
    ),
    EarthLevel(
        id="L2",
        centre=(0.0, 0.0),
        size_m=8_000.0,
        day_px=2048,
        height_px=512,
        water_px=2048,
        day_zoom=15,
        terrain_zoom=14,
        night_zoom=8,
        min_water_m2=10_000.0,
        road_kinds=MAJOR_ROADS + MINOR_ROADS,
        road_query_tiles=2,
        night_fabric=0.015,
    ),
)


# --- Web Mercator tile math -----------------------------------------------------------


def lnglat_to_px(
    lng: ArrayLike, lat: ArrayLike, zoom: int
) -> tuple[FloatArray, FloatArray]:
    """Continuous global Web Mercator pixel ``(px, py)``; pixel i spans [i, i+1)."""
    n = TILE_PX * 2.0**zoom
    lat_r = np.radians(np.asarray(lat, dtype=np.float64))
    px = (np.asarray(lng, dtype=np.float64) + 180.0) / 360.0 * n
    py = (1.0 - np.arcsinh(np.tan(lat_r)) / np.pi) / 2.0 * n
    return px, py


def px_to_lnglat(
    px: ArrayLike, py: ArrayLike, zoom: int
) -> tuple[FloatArray, FloatArray]:
    """Inverse of :func:`lnglat_to_px`."""
    n = TILE_PX * 2.0**zoom
    lng = np.asarray(px, dtype=np.float64) / n * 360.0 - 180.0
    lat = np.degrees(
        np.arctan(np.sinh(np.pi * (1.0 - 2.0 * np.asarray(py, dtype=np.float64) / n)))
    )
    return lng, lat


def mercator_m_per_px(lat: float, zoom: int) -> float:
    """Ground size (m) of one Web Mercator pixel at ``lat``."""
    return (
        WEB_MERCATOR_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / (TILE_PX * 2**zoom)
    )


@dataclass(frozen=True, slots=True)
class TileSpan:
    """Inclusive tile ranges ``x0..x1`` and ``y0..y1`` at one zoom."""

    zoom: int
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def shape_px(self) -> tuple[int, int]:
        """(rows, columns) of the stitched mosaic."""
        return (self.y1 - self.y0 + 1) * TILE_PX, (self.x1 - self.x0 + 1) * TILE_PX

    @property
    def origin_px(self) -> tuple[float, float]:
        """Global pixel ``(px, py)`` of the mosaic's top-left corner."""
        return float(self.x0 * TILE_PX), float(self.y0 * TILE_PX)

    def tiles(self) -> list[tuple[int, int]]:
        return [
            (x, y)
            for y in range(self.y0, self.y1 + 1)
            for x in range(self.x0, self.x1 + 1)
        ]


def tile_span(bbox: BBox, zoom: int, margin_px: float = 8.0) -> TileSpan:
    """Tiles covering ``bbox`` plus ``margin_px`` (interpolation and blur)."""
    px0, py0 = lnglat_to_px(bbox.west, bbox.north, zoom)
    px1, py1 = lnglat_to_px(bbox.east, bbox.south, zoom)
    last = 2**zoom - 1

    def tile(v: float) -> int:
        return min(max(math.floor(v / TILE_PX), 0), last)

    return TileSpan(
        zoom,
        tile(float(px0) - margin_px),
        tile(float(py0) - margin_px),
        tile(float(px1) + margin_px),
        tile(float(py1) + margin_px),
    )


# --- Terrarium codec ------------------------------------------------------------------


def terrarium_decode(rgb: ArrayLike) -> Float32Array:
    """Heights (m) from Terrarium RGB: ``R*256 + G + B/256 - 32768``."""
    c = np.asarray(rgb, dtype=np.float64)
    return (c[..., 0] * 256.0 + c[..., 1] + c[..., 2] / 256.0 - 32768.0).astype(
        np.float32
    )


def terrarium_encode(height_m: ArrayLike) -> ByteArray:
    """Terrarium RGB (uint8, ``(..., 3)``) rounded to 1/256 m."""
    q = np.rint((np.asarray(height_m, dtype=np.float64) + 32768.0) * 256.0)
    q = np.clip(q, 0, 2**24 - 1).astype(np.uint32)
    return np.stack([q >> 16, (q >> 8) & 255, q & 255], axis=-1).astype(np.uint8)


# --- local-metre grids ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Grid:
    """Square raster in local metres: row 0 is the north edge, column 0 the west."""

    west: float
    north: float
    step_m: float
    px: int

    @classmethod
    def of(cls, level: EarthLevel, px: int) -> Self:
        west, _, _, north = level.bounds
        return cls(west, north, level.size_m / px, px)

    def padded(self, pad_px: int) -> "Grid":
        return Grid(
            self.west - pad_px * self.step_m,
            self.north + pad_px * self.step_m,
            self.step_m,
            self.px + 2 * pad_px,
        )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(west, south, east, north)`` in local metres."""
        size = self.step_m * self.px
        return self.west, self.north - size, self.west + size, self.north

    def centres(self) -> tuple[FloatArray, FloatArray]:
        """x of each column (west to east) and y of each row (north to south)."""
        offsets = (np.arange(self.px, dtype=np.float64) + 0.5) * self.step_m
        return self.west + offsets, self.north - offsets

    def to_pixel(self, x: ArrayLike, y: ArrayLike) -> tuple[FloatArray, FloatArray]:
        """Continuous ``(column, row)``; pixel i spans [i, i+1)."""
        col = (np.asarray(x, dtype=np.float64) - self.west) / self.step_m
        row = (self.north - np.asarray(y, dtype=np.float64)) / self.step_m
        return col, row

    def lnglat(
        self, projector: LocalProjector, rows: slice = slice(None)
    ) -> tuple[FloatArray, FloatArray]:
        """``(lng, lat)`` of the pixel centres of ``rows``, shape (rows, px)."""
        xs, ys = self.centres()
        gx, gy = np.meshgrid(xs, ys[rows])
        return projector.to_wgs84_arrays(gx, gy)


def lnglat_bbox(
    bounds: tuple[float, float, float, float],
    projector: LocalProjector,
    samples: int = 65,
) -> BBox:
    """WGS84 envelope of a local-metre rectangle (edges sampled: UTM is curved)."""
    west, south, east, north = bounds
    t = np.linspace(0.0, 1.0, samples)
    span_x, span_y = east - west, north - south
    xs = np.concatenate(
        [
            west + t * span_x,
            np.full_like(t, east),
            east - t * span_x,
            np.full_like(t, west),
        ]
    )
    ys = np.concatenate(
        [
            np.full_like(t, south),
            south + t * span_y,
            np.full_like(t, north),
            north - t * span_y,
        ]
    )
    lng, lat = projector.to_wgs84_arrays(xs, ys)
    return BBox(
        south=float(lat.min()),
        west=float(lng.min()),
        north=float(lat.max()),
        east=float(lng.max()),
    )


def expand(
    bounds: tuple[float, float, float, float], margin_m: float
) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    return west - margin_m, south - margin_m, east + margin_m, north + margin_m


# --- tile download and cache ----------------------------------------------------------

_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def tile_cache_path(root: Path, source: TileSource, z: int, x: int, y: int) -> Path:
    return root / source.name / str(z) / str(x) / f"{y}.{source.ext}"


def _is_image(body: bytes) -> bool:
    try:
        with Image.open(BytesIO(body)) as img:
            img.load()
    except (OSError, ValueError):
        return False
    return True


def _download(
    url: str, attempts: int = 5, timeout_s: float = 60.0, backoff_s: float = 1.0
) -> bytes | None:
    """GET an image with exponential backoff; ``None`` if the server has none."""
    error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body: bytes = response.read()
            if response.status == 204 or not body:
                return None
            if _is_image(body):
                return body
            error = ValueError("response is not a decodable image")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in _RETRY_STATUS:
                raise
            error = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            error = exc
        time.sleep(min(30.0, backoff_s * 2**attempt))
    raise RuntimeError(f"giving up on {url} after {attempts} attempts: {error}")


def _fetch_tile(source: TileSource, z: int, x: int, y: int, root: Path) -> bool:
    """Make sure one tile is cached; ``False`` if the server has no such tile."""
    path = tile_cache_path(root, source, z, x, y)
    if path.is_file():
        return True
    body = _download(source.tile_url(z, x, y))
    if body is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(body)
    part.replace(path)  # atomic: an interrupted run never leaves a torn tile
    return True


def fetch_tiles(
    source: TileSource, span: TileSpan, root: Path, workers: int = MAX_WORKERS
) -> int:
    """Download the span's uncached tiles; returns how many were fetched."""
    if span.zoom > source.max_zoom:
        raise ValueError(
            f"{source.name} has no zoom {span.zoom} (max {source.max_zoom})"
        )
    todo = [
        t
        for t in span.tiles()
        if not tile_cache_path(root, source, span.zoom, *t).is_file()
    ]
    if not todo:
        return 0
    log.info(
        "%s z%d: downloading %d of %d tiles",
        source.name,
        span.zoom,
        len(todo),
        len(span.tiles()),
    )
    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_WORKERS))) as pool:
        found = list(
            pool.map(lambda t: _fetch_tile(source, span.zoom, t[0], t[1], root), todo)
        )
    missing = found.count(False)
    if missing:
        log.warning("%s z%d: %d tile(s) do not exist", source.name, span.zoom, missing)
    return len(todo) - missing


def stitch(source: TileSource, span: TileSpan, root: Path) -> ByteArray:
    """RGB mosaic of the cached tiles; absent tiles are ``source.fill``."""
    rows, cols = span.shape_px
    out = np.empty((rows, cols, 3), dtype=np.uint8)
    out[...] = source.fill
    for x, y in span.tiles():
        path = tile_cache_path(root, source, span.zoom, x, y)
        if not path.is_file():
            continue
        with Image.open(path) as img:
            tile = np.asarray(img.convert("RGB"))
        if tile.shape != (TILE_PX, TILE_PX, 3):
            raise ValueError(f"{path}: unexpected tile shape {tile.shape}")
        r, c = (y - span.y0) * TILE_PX, (x - span.x0) * TILE_PX
        out[r : r + TILE_PX, c : c + TILE_PX] = tile
    return out


# --- resampling -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mosaic:
    """Stitched tiles; ``data[r, c]`` covers global pixel ``origin + (c, r)``."""

    data: Float32Array  # (rows, columns, channels)
    zoom: int
    origin_px: tuple[float, float]


def mosaic_index(
    mosaic: Mosaic, lng: ArrayLike, lat: ArrayLike
) -> tuple[FloatArray, FloatArray]:
    """Fractional array ``(row, column)`` of ``lng``/``lat`` in the mosaic.

    Array index i is the sample at the pixel centre, global coordinate i + 0.5.
    """
    px, py = lnglat_to_px(lng, lat, mosaic.zoom)
    return py - mosaic.origin_px[1] - 0.5, px - mosaic.origin_px[0] - 0.5


def antialias_sigma(src_m_per_px: float, out_m_per_px: float) -> float:
    """Gaussian prefilter (source px) before downsampling; 0 when upsampling."""
    ratio = out_m_per_px / src_m_per_px
    return 0.5 * math.sqrt(max(ratio * ratio - 1.0, 0.0))


def blurred(mosaic: Mosaic, sigma_px: float) -> Mosaic:
    if sigma_px <= 0:
        return mosaic
    data = ndimage.gaussian_filter(mosaic.data, sigma=(sigma_px, sigma_px, 0))
    return Mosaic(data.astype(np.float32), mosaic.zoom, mosaic.origin_px)


def resample(
    mosaic: Mosaic,
    grid: Grid,
    projector: LocalProjector,
    order: int = 1,
    block_rows: int = 512,
) -> Float32Array:
    """Sample the mosaic at every grid pixel centre: ``(px, px, channels)``.

    ``order`` 1 is bilinear, 3 bicubic (B-spline).
    """
    channels = [
        np.ascontiguousarray(mosaic.data[..., c]) for c in range(mosaic.data.shape[2])
    ]
    mode = "nearest" if order <= 1 else "mirror"
    if order > 1:
        channels = [
            ndimage.spline_filter(ch, order=order, mode=mode).astype(np.float32)
            for ch in channels
        ]
    out = np.empty((grid.px, grid.px, len(channels)), dtype=np.float32)
    for start in range(0, grid.px, block_rows):
        rows = slice(start, min(start + block_rows, grid.px))
        lng, lat = grid.lnglat(projector, rows)
        coords = np.stack(mosaic_index(mosaic, lng, lat))
        for c, ch in enumerate(channels):
            out[rows, :, c] = ndimage.map_coordinates(
                ch, coords, order=order, mode=mode, prefilter=False
            )
    return out


def load_mosaic(
    source: TileSource,
    bbox: BBox,
    zoom: int,
    root: Path,
    workers: int = MAX_WORKERS,
) -> tuple[Mosaic, ByteArray]:
    """Fetch, cache and stitch the tiles over ``bbox``: (float mosaic, raw RGB)."""
    span = tile_span(bbox, zoom)
    fetch_tiles(source, span, root, workers)
    rgb = stitch(source, span, root)
    return Mosaic(rgb.astype(np.float32), zoom, span.origin_px), rgb


# --- vector rasterisation -------------------------------------------------------------


def supersample_for(px: int, limit: int = 12_288, most: int = 4) -> int:
    """Largest supersampling factor (<= ``most``) keeping the canvas <= ``limit``."""
    return max(1, min(most, limit // px))


def _canvas_xy(coords: Iterable[Sequence[float]], grid: Grid, k: int) -> FloatArray:
    """Continuous canvas ``(u, v)`` at ``k`` x supersampling; pixel i spans [i, i+1)."""
    xy = np.asarray(list(coords), dtype=np.float64)[:, :2]
    col, row = grid.to_pixel(xy[:, 0], xy[:, 1])
    return np.column_stack([col * k, row * k])


def _line_coords(
    coords: Iterable[Sequence[float]], grid: Grid, k: int
) -> list[tuple[float, float]]:
    """Pillow line coordinates (Pillow truncates, so wide lines stay centred)."""
    return [(float(u), float(v)) for u, v in _canvas_xy(coords, grid, k)]


def _downsample(canvas: NDArray[Any], k: int, scale: float = 1.0) -> Float32Array:
    a = np.asarray(canvas, dtype=np.float32) * scale
    if k == 1:
        return a
    n = a.shape[0] // k
    return a.reshape(n, k, n, k).mean(axis=(1, 3), dtype=np.float32)


def fill_rings(rings: Sequence[FloatArray], size: int) -> NDArray[np.uint8]:
    """Even-odd scanline fill sampled at pixel centres (1 inside, 0 outside).

    ``rings`` are closed ``(n, 2)`` arrays of canvas ``(u, v)``. Each edge
    toggles, on every row whose centre it crosses, the first pixel whose centre
    lies right of the crossing; an XOR prefix along each row then marks the
    inside. Holes and polygons nested in holes need no special ordering.
    """
    toggles = np.zeros((size, size + 1), dtype=np.uint8)  # +1: crossings past the edge
    closed = [r for r in rings if len(r) >= 3]
    if closed:
        a = np.vstack([r[:-1] for r in closed])
        b = np.vstack([r[1:] for r in closed])
        lo = np.clip(np.ceil(np.minimum(a[:, 1], b[:, 1]) - 0.5), 0, size)
        hi = np.clip(np.ceil(np.maximum(a[:, 1], b[:, 1]) - 0.5), 0, size)
        count = (hi - lo).astype(np.int64)  # rows whose centre the edge crosses
        edge = np.repeat(np.arange(len(a)), count)
        first = np.repeat(np.cumsum(count) - count, count)
        row = lo[edge].astype(np.int64) + np.arange(len(edge)) - first
        t = (row + 0.5 - a[edge, 1]) / (b[edge, 1] - a[edge, 1])
        u = a[edge, 0] + t * (b[edge, 0] - a[edge, 0])
        col = np.clip(np.ceil(u - 0.5), 0, size).astype(np.int64)
        flat, hits = np.unique(row * (size + 1) + col, return_counts=True)
        toggles.reshape(-1)[flat[hits % 2 == 1]] = 1
    return np.bitwise_xor.accumulate(toggles, axis=1)[:, :size]


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [] if geometry.is_empty else [geometry]
    out: list[Polygon] = []
    for part in getattr(geometry, "geoms", []):
        out.extend(_polygon_parts(part))
    return out


def rasterize_polygons(
    geometry: BaseGeometry, grid: Grid, supersample: int | None = None
) -> Float32Array:
    """Anti-aliased coverage in [0, 1] of non-overlapping polygons on ``grid``."""
    k = supersample or supersample_for(grid.px)
    frame = box(*expand(grid.bounds, 2 * grid.step_m))
    clipped = geometry.intersection(frame).simplify(
        grid.step_m / k / 4, preserve_topology=True
    )
    rings = [
        _canvas_xy(ring.coords, grid, k)
        for part in _polygon_parts(clipped)
        for ring in (part.exterior, *part.interiors)
    ]
    return _downsample(fill_rings(rings, grid.px * k), k)


# --- water ----------------------------------------------------------------------------


def shore_distance_m(
    water: NDArray[np.bool_], step_m: float, max_m: float = SHORE_MAX_M
) -> Float32Array:
    """Distance (m) from each water pixel to the nearest land, clamped; 0 on land.

    The shore lies half a pixel from the centre of the first water pixel.
    """
    if not water.any():
        return np.zeros(water.shape, dtype=np.float32)
    if water.all():
        return np.full(water.shape, max_m, dtype=np.float32)
    edt = np.asarray(ndimage.distance_transform_edt(water), dtype=np.float64)
    dist = edt * step_m - 0.5 * step_m
    dist = np.clip(dist, 0.0, max_m).astype(np.float32)
    dist[~water] = 0.0
    return dist


def water_texture(
    coverage: Float32Array, distance_m: Float32Array, max_m: float = SHORE_MAX_M
) -> ByteArray:
    """RGB: R water coverage, G shore distance (0..max_m -> 0..255), B 0."""
    out = np.zeros((*coverage.shape, 3), dtype=np.uint8)
    out[..., 0] = np.rint(np.clip(coverage, 0.0, 1.0) * 255.0)
    out[..., 1] = np.rint(np.clip(distance_m / max_m, 0.0, 1.0) * 255.0)
    return out


@dataclass(frozen=True, slots=True)
class WaterSet:
    """Sea (coastline split) and inland water bodies, local metres."""

    sea: BaseGeometry
    bodies: Mapping[str, Sequence[Polygon]]  # level id -> water bodies
    used_natural_earth: bool

    def lakes(self, level: EarthLevel) -> BaseGeometry:
        """The level's inland water bodies above its area threshold."""
        return unary_union(
            [p for p in self.bodies.get(level.id, ()) if p.area >= level.min_water_m2]
        )

    def for_level(self, level: EarthLevel) -> BaseGeometry:
        """Sea plus the level's inland water bodies."""
        return unary_union([self.sea, self.lakes(level)])


# --- terrain --------------------------------------------------------------------------


def finish_heights(
    heights: Float32Array,
    sea: NDArray[np.bool_],
    lakes: NDArray[np.bool_] | None = None,
    smooth_px: float = 0.0,
    step_m: float = HEIGHT_STEP_M,
) -> Float32Array:
    """Sea exactly 0 m, each lake flat at its own level, land >= 0.5 m.

    Inland water is not at sea level (reservoirs sit 5-80 m up): every
    connected lake region is flattened to the median terrain height inside it
    instead of being carved down to 0 m. Heights are rounded to ``step_m``.
    """
    if smooth_px > 0:
        heights = ndimage.gaussian_filter(heights, smooth_px).astype(np.float32)
    out = np.maximum(heights, LAND_MIN_M)
    if lakes is not None:
        inland = lakes & ~sea
        labelled: Any = ndimage.label(inland)  # the stubs do not narrow the union
        labels = np.asarray(labelled[0], dtype=np.int64)
        count = int(labelled[1])
        if count:
            index = np.arange(1, count + 1)
            levels = np.asarray(ndimage.median(heights, labels, index), np.float64)
            per_label = np.concatenate([[0.0], np.maximum(levels, 0.0)])
            out = np.where(inland, per_label[labels], out)
    if step_m > 0:
        out = np.round(out / step_m) * step_m
    return np.where(sea, 0.0, out).astype(np.float32)


# --- night lights ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadLight:
    width_m: float  # lit width: lamps spill past the carriageway
    intensity: float  # relative brightness per lit pixel
    tint: tuple[float, float, float]  # linear RGB


LED = (1.0, 0.72, 0.42)  # warm-white LED, sRGB ~(255, 220, 172), linear
SODIUM = (1.0, 0.36, 0.06)  # high-pressure sodium, sRGB ~(255, 160, 70), linear

ROAD_LIGHTS: Mapping[str, RoadLight] = {
    "motorway": RoadLight(14.0, 1.0, LED),
    "trunk": RoadLight(12.0, 0.95, LED),
    "motorway_link": RoadLight(7.0, 0.75, LED),
    "trunk_link": RoadLight(7.0, 0.7, LED),
    "primary": RoadLight(10.0, 0.85, SODIUM),
    "primary_link": RoadLight(7.0, 0.7, SODIUM),
    "secondary": RoadLight(8.0, 0.75, SODIUM),
    "secondary_link": RoadLight(6.0, 0.6, SODIUM),
    "tertiary": RoadLight(7.0, 0.6, SODIUM),
    "tertiary_link": RoadLight(5.0, 0.5, SODIUM),
    "residential": RoadLight(4.5, 0.45, SODIUM),
    "unclassified": RoadLight(4.5, 0.4, SODIUM),
    "living_street": RoadLight(4.0, 0.35, SODIUM),
}
ROAD_GLOW_SIGMA_M = 15.0
ROAD_CORE_GAIN = 0.8
ROAD_GLOW_GAIN = 1.0
# Street lamps read as beads along a road: a fixed-seed speckle of this size
# modulates the road cores where pixels are small enough to show it.
LAMP_SPECKLE_M = 10.0
LAMP_SPECKLE_DEPTH = 0.7
LAMP_SEED = 20_241_006
NIGHT_BLUR_PX = 1.0  # Black Marble source pixels, against blockiness

# Night model: Black Marble (~500 m) says how much light an area emits; the OSM
# roads and the built-up fabric of the day image say where inside it the light
# comes from. The emitted light is redistributed over that "light density"
# while its local mean (over NIGHT_SPREAD_M) is conserved, so a level seen from
# afar matches the coarser one and unlit land stays dark.
NIGHT_GAMMA = 2.2  # 8-bit sRGB <-> linear light
NIGHT_BG_LUMA = 0.006  # linear luma of Black Marble's moonlit-land background
NIGHT_SPREAD_M = 350.0
NIGHT_KNEE = 0.6  # linear level where the soft highlight roll-off starts
# Black Marble's city cores are clipped white in 8 bits: scale the emitted
# light down and pull its hue towards warm street lighting.
NIGHT_EXPOSURE = 0.32
NIGHT_TINT = (1.0, 0.42, 0.10)  # linear, sRGB ~(255, 172, 90)
NIGHT_TINT_MIX = 0.9
NIGHT_AMBIENT = 0.6  # weight of Black Marble's moonlit-land background
# Linear Black Marble luma over which emission fades in: the faint halo that
# Black Marble's 500 m pixels spread over forest and sea is not real light.
EMIT_RAMP = (0.015, 0.14)
FABRIC_FLOOR = 0.15  # unbuilt land (parks) as a share of the built-up density
# Below this local light density the light is not concentrated further, so
# open ground far from any road (airfields, fields) does not glow.
NIGHT_MEAN_MIN = 0.2
ROAD_WEIGHT = 3.0  # road light density per unit of rendered road light
BUILT_LUMA = (0.12, 0.45)  # day luminance: dark vegetation .. bright roofs
BUILT_GREEN = (0.0, 0.05)  # day G - R above which a pixel reads as vegetation
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


@dataclass(frozen=True, slots=True)
class LitRoad:
    kind: str
    bridge: bool
    line: LineString  # local metres


def patiently[T](
    call: Callable[[], T],
    rounds: int = OVERPASS_ROUNDS,
    wait_s: float = OVERPASS_ROUND_WAIT_S,
) -> T:
    """Retry an Overpass fetch through busy spells (cached fetches return at once)."""
    for attempt in range(1, rounds + 1):
        try:
            return call()
        except RuntimeError as exc:
            if attempt == rounds:
                raise
            log.warning("Overpass busy (round %d/%d): %s", attempt, rounds, exc)
            time.sleep(wait_s * attempt)
    raise AssertionError("unreachable")


def split_bbox(bbox: BBox, n: int) -> list[BBox]:
    """``n`` x ``n`` sub-boxes of ``bbox``, south-west first, row by row."""
    lat = np.linspace(bbox.south, bbox.north, n + 1).tolist()
    lng = np.linspace(bbox.west, bbox.east, n + 1).tolist()
    return [
        BBox(south=lat[i], west=lng[j], north=lat[i + 1], east=lng[j + 1])
        for i in range(n)
        for j in range(n)
    ]


def fetch_roads_tiled(
    bbox: BBox, kinds: Iterable[str], cache_stem: Path, tiles: int = 1
) -> dict[str, Any]:
    """Highways over ``tiles`` x ``tiles`` Overpass queries, merged by way id.

    Dense city boxes time out as one query; each piece is cached on its own
    (``<stem>_<i>.json``), so an interrupted run resumes where it stopped.
    """
    kinds = tuple(kinds)
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for index, part in enumerate(split_bbox(bbox, tiles)):
        cache = cache_stem.with_name(f"{cache_stem.name}_{index}.json")
        raw = patiently(
            partial(fetch_roads_raw, part, cache, kinds, ROAD_OVERPASS_TIMEOUT_S)
        )
        for element in raw.get("elements", []):
            merged.setdefault((element.get("type", ""), element.get("id", 0)), element)
    return {"elements": list(merged.values())}


def parse_lit_roads(
    payload: dict[str, Any], projector: LocalProjector, kinds: Iterable[str]
) -> list[LitRoad]:
    """Highways of ``kinds`` (one vectorised projection), with a bridge flag."""
    wanted = frozenset(kinds)
    ways = [
        el
        for el in payload.get("elements", [])
        if el.get("type") == "way"
        and el.get("tags", {}).get("highway") in wanted
        and len(el.get("geometry", [])) >= 2
    ]
    if not ways:
        return []
    points = [p for el in ways for p in el["geometry"]]
    x, y = projector.to_local_arrays(
        np.array([p["lon"] for p in points]), np.array([p["lat"] for p in points])
    )
    xy = np.column_stack([x, y])
    bounds = np.cumsum([0] + [len(el["geometry"]) for el in ways]).tolist()
    roads: list[LitRoad] = []
    for el, (a, b) in zip(ways, pairwise(bounds), strict=True):
        tags: dict[str, str] = el["tags"]
        bridge = tags.get("bridge", "no") != "no"
        roads.append(LitRoad(tags["highway"], bridge, LineString(xy[a:b])))
    return roads


def lamp_speckle(grid: Grid) -> Float32Array:
    """Deterministic 0..1 multiplier: lamp-sized bright beads, or 1 if too coarse."""
    sigma_px = LAMP_SPECKLE_M / grid.step_m / 2
    if sigma_px < 0.5:
        return np.ones((grid.px, grid.px), dtype=np.float32)
    noise = np.random.default_rng(LAMP_SEED).random((grid.px, grid.px))
    field = ndimage.gaussian_filter(noise.astype(np.float32), sigma_px, mode="wrap")
    lo, hi = np.percentile(field, [2.0, 98.0])
    t = np.clip((field - lo) / max(float(hi - lo), 1e-6), 0.0, 1.0)
    return (1.0 - LAMP_SPECKLE_DEPTH + LAMP_SPECKLE_DEPTH * t).astype(np.float32)


def render_road_lights(
    roads: Sequence[LitRoad], grid: Grid, supersample: int | None = None
) -> tuple[Float32Array, Float32Array]:
    """``(land, bridge)`` RGB light layers: anti-aliased cores plus a soft glow."""
    k = supersample or supersample_for(grid.px, limit=8192)
    size = grid.px * k
    glow_px = ROAD_GLOW_SIGMA_M / grid.step_m
    speckle = lamp_speckle(grid)
    layers: list[Float32Array] = []
    for bridge in (False, True):
        rgb = np.zeros((grid.px, grid.px, 3), dtype=np.float32)
        for tint in (LED, SODIUM):
            group = sorted(
                (
                    r
                    for r in roads
                    if r.bridge == bridge and ROAD_LIGHTS[r.kind].tint == tint
                ),
                key=lambda r: ROAD_LIGHTS[r.kind].intensity,
            )
            if not group:
                continue
            canvas = Image.new("L", (size, size), 0)
            draw = ImageDraw.Draw(canvas)
            for road in group:  # dim first: brighter roads win at junctions
                light = ROAD_LIGHTS[road.kind]
                width = max(1, round(light.width_m / grid.step_m * k))
                draw.line(
                    _line_coords(road.line.coords, grid, k),
                    fill=round(255 * light.intensity),
                    width=width,
                    joint="curve",
                )
            core = _downsample(np.asarray(canvas), k, 1 / 255) * speckle
            glow = ndimage.gaussian_filter(core, glow_px)
            rgb += (ROAD_CORE_GAIN * core + ROAD_GLOW_GAIN * glow)[
                ..., None
            ] * np.array(tint, dtype=np.float32)
        layers.append(rgb)
    return layers[0], layers[1]


def smoothstep(lo: float, hi: float, x: ArrayLike) -> Float32Array:
    t = np.clip((np.asarray(x, dtype=np.float32) - lo) / (hi - lo), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def built_up(day_rgb: ArrayLike) -> Float32Array:
    """0..1 built-up fabric from day imagery: bright, not green (roofs, paving)."""
    rgb = np.asarray(day_rgb, dtype=np.float32) / 255.0
    luma = rgb @ _LUMA
    green = rgb[..., 1] - rgb[..., 0]
    vegetation = smoothstep(*BUILT_GREEN, green)
    return (smoothstep(*BUILT_LUMA, luma) * (1.0 - vegetation)).astype(np.float32)


def wide_blur(a: NDArray[Any], sigma_px: float) -> Float32Array:
    """Gaussian blur; wide kernels run on a block-averaged copy, then upsample."""
    if sigma_px <= 0:
        return a.astype(np.float32)
    factor = max(1, int(sigma_px // 6))
    while a.shape[0] % factor or a.shape[1] % factor:
        factor -= 1
    if factor == 1:
        return ndimage.gaussian_filter(a, sigma_px, mode="nearest").astype(np.float32)
    rows, cols = a.shape[0] // factor, a.shape[1] // factor
    small = a.reshape(rows, factor, cols, factor).mean(axis=(1, 3))
    small = ndimage.gaussian_filter(small, sigma_px / factor, mode="nearest")
    big = ndimage.zoom(small, factor, order=1, mode="nearest", grid_mode=True)
    return np.asarray(big, dtype=np.float32)


def tone_map(rgb: Float32Array) -> Float32Array:
    """Hue-preserving highlight roll-off on luma, then clip to [0, 1]."""
    luma = rgb @ _LUMA
    scale = soft_knee(luma) / np.maximum(luma, 1e-6)
    return np.clip(rgb * scale[..., None], 0.0, 1.0).astype(np.float32)


def soft_knee(x: ArrayLike, knee: float = NIGHT_KNEE) -> Float32Array:
    """Identity below ``knee``, exponential roll-off towards 1 above it."""
    a = np.maximum(np.asarray(x, dtype=np.float32), 0.0)
    span = 1.0 - knee
    rolled = knee + span * (1.0 - np.exp(-(a - knee) / span))
    return np.where(a <= knee, a, rolled).astype(np.float32)


def _night_hue(bm: Float32Array, luma: Float32Array) -> Float32Array:
    """Unit-luma colour of the emitted light: Black Marble hue warmed up."""
    tint = np.array(NIGHT_TINT, dtype=np.float32)
    own = bm / np.maximum(luma, 1e-6)[..., None]
    hue = (1.0 - NIGHT_TINT_MIX) * own + NIGHT_TINT_MIX * tint / float(tint @ _LUMA)
    return (hue / np.maximum(hue @ _LUMA, 1e-6)[..., None]).astype(np.float32)


def redistribute(
    light: Float32Array,
    emit: Float32Array,
    fabric: Float32Array,
    road: Float32Array,
    spread_px: float,
) -> Float32Array:
    """Emitted light moved onto the fabric and roads, its local mean conserved.

    ``light`` is the emitted RGB (luma ``emit``), ``fabric`` a scalar light
    density and ``road`` an RGB one. Each pixel gets its density over the mean
    density within ``spread_px``; sparse areas (mean below ``NIGHT_MEAN_MIN``)
    are not concentrated further, so lone roads in the dark stay dim.
    """
    mean = wide_blur(fabric + road @ _LUMA, spread_px)
    gain = (1.0 / np.maximum(mean, NIGHT_MEAN_MIN))[..., None]
    lit = light * fabric[..., None] + emit[..., None] * road
    return (gain * lit).astype(np.float32)


def compose_night(
    black_marble: Float32Array,
    water: Float32Array,
    roads: tuple[Float32Array, Float32Array] | None = None,
    built: Float32Array | None = None,
    spread_px: float = 0.0,
    fabric_weight: float = 0.12,
) -> ByteArray:
    """Night RGB (8-bit sRGB) from Black Marble (0..1 sRGB) and light sources.

    Black Marble is split into its moonlit background and the light the area
    emits (exposed and warmed, identically on every level). Without ``roads``
    and ``built`` the emitted light stays where Black Marble puts it. With them
    it is moved onto the built-up fabric and the road lights (``(land,
    bridge)`` layers), its mean over ``spread_px`` conserved. Water is black
    except for bridges.
    """
    land = (1.0 - np.clip(water, 0.0, 1.0)).astype(np.float32)
    bm = (np.clip(black_marble, 0.0, 1.0) ** NIGHT_GAMMA).astype(np.float32)
    luma = bm @ _LUMA
    emit = (
        np.maximum(luma - NIGHT_BG_LUMA, 0.0)
        * smoothstep(*EMIT_RAMP, luma)
        * NIGHT_EXPOSURE
    )
    background = np.minimum(luma, NIGHT_BG_LUMA) / np.maximum(luma, 1e-6)
    ambient = bm * (NIGHT_AMBIENT * background)[..., None]
    light = emit[..., None] * _night_hue(bm, luma)
    if roads is None and built is None:
        total = (ambient + light) * land[..., None]
    else:
        built_px = np.zeros_like(land) if built is None else built
        fabric = fabric_weight * (FABRIC_FLOOR + (1 - FABRIC_FLOOR) * built_px) * land
        road = np.zeros_like(bm)
        if roads is not None:
            road = ROAD_WEIGHT * (roads[0] * land[..., None] + roads[1])
        total = ambient * land[..., None] + redistribute(
            light, emit, fabric.astype(np.float32), road, spread_px
        )
    srgb = tone_map(np.asarray(total, dtype=np.float32)) ** (1.0 / NIGHT_GAMMA)
    return np.rint(np.clip(srgb, 0.0, 1.0) * 255.0).astype(np.uint8)


# --- manifest -------------------------------------------------------------------------


def manifest(
    levels: Sequence[EarthLevel],
    height_range_m: tuple[float, float],
    attribution: Sequence[str],
) -> dict[str, Any]:
    """``earth.json``: files are relative to the manifest's directory."""
    return {
        "version": MANIFEST_VERSION,
        "crs": CRS_ID,
        "origin": {"lat": CAMPUS_ORIGIN_LAT, "lng": CAMPUS_ORIGIN_LNG},
        "levels": [
            {
                "id": lv.id,
                "centre": [lv.centre[0], lv.centre[1]],
                "size_m": lv.size_m,
                "day": {"file": lv.file("day"), "px": lv.day_px},
                "night": {"file": lv.file("night"), "px": lv.day_px},
                "height": {
                    "file": lv.file("height"),
                    "px": lv.height_px,
                    "encoding": "terrarium",
                },
                "water": {
                    "file": lv.file("water"),
                    "px": lv.water_px,
                    "shore_max_m": SHORE_MAX_M,
                },
            }
            for lv in levels
        ],
        "height_range_m": [round(height_range_m[0], 2), round(height_range_m[1], 2)],
        "attribution": list(attribution),
    }


# --- pipeline -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EarthPaths:
    out_dir: Path
    tile_cache: Path
    osm_dir: Path
    natural_earth: Path

    @classmethod
    def under(cls, data_dir: Path) -> Self:
        return cls(
            out_dir=data_dir / "out" / "earth",
            tile_cache=data_dir / "cache" / "earth",
            osm_dir=data_dir / "osm",
            natural_earth=data_dir / "natural_earth" / "ne_10m_land.geojson",
        )


def load_water(
    paths: EarthPaths, levels: Sequence[EarthLevel], projector: LocalProjector
) -> WaterSet:
    """Sea from the OSM coastline (Natural Earth for untouched faces) + lakes."""
    largest = max(levels, key=lambda lv: lv.size_m)
    frame_bounds = expand(largest.bounds, COAST_MARGIN_M)
    frame = box(*frame_bounds)
    bbox = lnglat_bbox(frame_bounds, projector)
    try:
        raw = patiently(
            lambda: fetch_coastline_raw(
                bbox, paths.osm_dir / "earth_coastline.json", OVERPASS_TIMEOUT_S
            )
        )
        lines = coastline_lines(raw, projector)
    except RuntimeError as exc:
        log.warning("OSM coastline unavailable (%s); using Natural Earth", exc)
        lines = []
    log.info("coastline: %d ways; cutting the frame", len(lines))
    faces = coastline_faces(lines, frame)
    fallback: BaseGeometry | None = None
    if any(face.vote == 0 for face in faces):
        land_ne = parse_land(
            fetch_land_raw(paths.natural_earth), projector, bbox, tolerance_m=30.0
        )
        fallback = unary_union(land_ne)
    _, sea = classify_faces(faces, fallback)
    bodies: dict[str, list[Polygon]] = {}
    for level in levels:
        regional = level.min_water_m2 >= 100_000.0
        water_bbox = lnglat_bbox(expand(level.bounds, COAST_MARGIN_M), projector)
        cache = paths.osm_dir / f"earth_water_{level.id}.json"
        skip = MINOR_WATER_KINDS if regional else ()
        raw_bodies = patiently(
            partial(fetch_water_bodies_raw, water_bbox, cache, skip, OVERPASS_TIMEOUT_S)
        )
        bodies[level.id] = parse_water_bodies(raw_bodies, projector)
        log.info("%s: %d water bodies", level.id, len(bodies[level.id]))
    return WaterSet(unary_union(sea), bodies, fallback is not None)


def _save_webp(path: Path, rgb: ByteArray, quality: int) -> None:
    Image.fromarray(rgb, "RGB").save(path, "WEBP", quality=quality, method=6)


def _save_png(path: Path, rgb: ByteArray) -> None:
    Image.fromarray(rgb, "RGB").save(path, "PNG", optimize=True)


def _to_bytes(rgb: Float32Array) -> ByteArray:
    return np.rint(np.clip(rgb, 0.0, 255.0)).astype(np.uint8)


def _centre_lat(level: EarthLevel, projector: LocalProjector) -> float:
    return projector.to_wgs84(*level.centre)[1]


def _mosaic_for(
    source: TileSource,
    level: EarthLevel,
    zoom: int,
    out_m_per_px: float,
    paths: EarthPaths,
    projector: LocalProjector,
    workers: int,
) -> Mosaic:
    bbox = lnglat_bbox(level.bounds, projector)
    mosaic, rgb = load_mosaic(source, bbox, zoom, paths.tile_cache, workers)
    if source is TERRARIUM:
        mosaic = Mosaic(terrarium_decode(rgb)[..., None], zoom, mosaic.origin_px)
    src_m = mercator_m_per_px(_centre_lat(level, projector), zoom)
    return blurred(mosaic, antialias_sigma(src_m, out_m_per_px))


def build_level(
    level: EarthLevel,
    water_set: WaterSet,
    paths: EarthPaths,
    projector: LocalProjector,
    workers: int = MAX_WORKERS,
) -> tuple[float, float]:
    """Write the four textures of one level; returns its (min, max) height."""
    out = paths.out_dir
    water_geom = water_set.for_level(level)

    # Day.
    day_grid = Grid.of(level, level.day_px)
    eox = _mosaic_for(
        EOX_S2, level, level.day_zoom, day_grid.step_m, paths, projector, workers
    )
    day_rgb = _to_bytes(resample(eox, day_grid, projector))
    _save_webp(out / level.file("day"), day_rgb, level.day_quality)
    del eox
    log.info("%s: day written", level.id)

    # Night.
    bm_mosaic, _ = load_mosaic(
        BLACK_MARBLE,
        lnglat_bbox(level.bounds, projector),
        level.night_zoom,
        paths.tile_cache,
        workers,
    )
    bm = resample(blurred(bm_mosaic, NIGHT_BLUR_PX), day_grid, projector, order=3)
    bm = np.clip(bm / 255.0, 0.0, 1.0)
    water_day = rasterize_polygons(water_geom, day_grid)
    roads: tuple[Float32Array, Float32Array] | None = None
    if level.road_kinds:
        raw = fetch_roads_tiled(
            lnglat_bbox(level.bounds, projector),
            level.road_kinds,
            paths.osm_dir / f"earth_roads_{level.id}",
            level.road_query_tiles,
        )
        lit = parse_lit_roads(raw, projector, level.road_kinds)
        log.info("%s: %d lit road ways", level.id, len(lit))
        roads = render_road_lights(lit, day_grid)
    built = built_up(day_rgb) if level.road_kinds else None
    spread_px = NIGHT_SPREAD_M / day_grid.step_m
    night = compose_night(bm, water_day, roads, built, spread_px, level.night_fabric)
    _save_webp(out / level.file("night"), night, level.night_quality)
    del bm, water_day, roads, built, night, day_rgb
    log.info("%s: night written", level.id)

    # Height.
    height_grid = Grid.of(level, level.height_px)
    terrain = _mosaic_for(
        TERRARIUM,
        level,
        level.terrain_zoom,
        height_grid.step_m,
        paths,
        projector,
        workers,
    )
    heights = finish_heights(
        resample(terrain, height_grid, projector)[..., 0],
        rasterize_polygons(water_set.sea, height_grid) >= 0.5,
        rasterize_polygons(water_set.lakes(level), height_grid) >= 0.5,
        level.height_smooth_px,
    )
    encoded = terrarium_encode(heights)
    _save_png(out / level.file("height"), encoded)
    decoded = terrarium_decode(encoded)
    log.info("%s: height written", level.id)

    # Water: rasterised with a margin so the shore distance sees past the edge.
    water_grid = Grid.of(level, level.water_px)
    pad = math.ceil(SHORE_MAX_M / water_grid.step_m) + 1
    coverage = rasterize_polygons(water_geom, water_grid.padded(pad))
    distance = shore_distance_m(coverage >= 0.5, water_grid.step_m)
    inner = slice(pad, pad + water_grid.px)
    _save_png(
        out / level.file("water"),
        water_texture(coverage[inner, inner], distance[inner, inner]),
    )
    log.info("%s: water written", level.id)
    return float(decoded.min()), float(decoded.max())


def attribution(water_set: WaterSet) -> list[str]:
    credits = [
        EOX_S2.attribution,
        BLACK_MARBLE.attribution,
        TERRARIUM.attribution,
        OSM_ATTRIBUTION,
    ]
    if water_set.used_natural_earth:
        credits.append(NATURAL_EARTH_ATTRIBUTION)
    return credits


def build_earth(
    paths: EarthPaths,
    levels: Sequence[EarthLevel] = LEVELS,
    workers: int = MAX_WORKERS,
) -> list[Path]:
    """Write every level and ``earth.json``; returns the written files."""
    projector = LocalProjector()
    paths.out_dir.mkdir(parents=True, exist_ok=True)
    water_set = load_water(paths, levels, projector)
    lo, hi = math.inf, -math.inf
    for level in levels:
        level_lo, level_hi = build_level(level, water_set, paths, projector, workers)
        lo, hi = min(lo, level_lo), max(hi, level_hi)
    data = manifest(levels, (lo, hi), attribution(water_set))
    manifest_path = paths.out_dir / "earth.json"
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    files = [paths.out_dir / lv.file(layer) for lv in levels for layer in _LAYERS]
    return [*files, manifest_path]


_LAYERS = ("day", "night", "height", "water")
