"""Request/response models of the public API (exported to OpenAPI -> TypeScript)."""

from pydantic import BaseModel, Field

from amap_api.routing import Turn
from amap_contracts.graph import NodeKind


class Health(BaseModel):
    status: str
    graph_loaded: bool
    nodes: int
    edges: int
    version: str


class PlaceOut(BaseModel):
    id: str = Field(description="Node id of the representative panorama")
    name_tr: str
    name_en: str
    kind: NodeKind
    building: str | None
    node_ids: list[str]


class NearestNode(BaseModel):
    node_id: str
    distance_m: float


class RouteRequest(BaseModel):
    source: str = Field(description="Start node id (a place id is a node id)")
    target: str = Field(description="Destination node id")
    avoid_stairs: bool = False


class StepOut(BaseModel):
    node_id: str
    turn: Turn
    distance_m: float
    bearing_deg: float
    text_tr: str
    text_en: str


class RouteResponse(BaseModel):
    node_ids: list[str]
    length_m: float
    duration_s: float
    coordinates: list[tuple[float, float]] = Field(description="[lng, lat] per node")
    steps: list[StepOut]


class WeatherOut(BaseModel):
    observed_at: str
    temperature_c: float
    weather_code: int = Field(description="WMO weather interpretation code")
    cloud_cover_pct: float
    precipitation_mm: float
    wind_speed_kmh: float
    wind_direction_deg: float
    visibility_m: float
    is_day: bool
    stale: bool
    attribution: str


class ErrorOut(BaseModel):
    detail: str
