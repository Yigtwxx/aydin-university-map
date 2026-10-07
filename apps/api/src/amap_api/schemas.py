"""Request/response models of the public API (exported to OpenAPI -> TypeScript)."""

from typing import Literal

from pydantic import BaseModel, Field

from amap_api.routing import Turn
from amap_contracts.graph import LocalizedText, NodeKind
from amap_contracts.pois import PinSource, PoiCategory


class Health(BaseModel):
    status: str
    graph_loaded: bool
    nodes: int
    edges: int
    database: Literal["ok", "unavailable", "off"]
    version: str


class BuildingOut(BaseModel):
    id: str = Field(description="OSM way id")
    code: str | None = Field(description="Campus block letter, e.g. A")
    name: str | None
    campus: bool
    height_m: float
    height_source: str = Field(description="osm_levels | default | sfm")
    lng: float
    lat: float


class PlaceOut(BaseModel):
    id: str = Field(description="Node id of the representative panorama")
    name_tr: str
    name_en: str
    kind: NodeKind
    building: str | None
    node_ids: list[str]
    floor: int | None = Field(
        default=None, description="Storey of a room (kind indoor), when known"
    )
    area_tr: str = Field(default="", description="Tour area, e.g. Kimya - M Blok")
    area_en: str = ""
    category: PoiCategory | None = Field(
        default=None, description="Set for businesses and services (POIs)"
    )
    brand: str | None = None
    aliases: list[str] = Field(default_factory=list)
    pin_enu: tuple[float, float] | None = Field(
        default=None,
        description="Storefront in local metres (east, north) where measured",
    )
    pin_source: PinSource | None = Field(
        default=None,
        description="storefront (surveyed), entrance (its building's door), manual",
    )


class NearestNode(BaseModel):
    node_id: str
    distance_m: float


class RouteRequest(BaseModel):
    source: str = Field(description="Start node id or place id (poi:<slug>)")
    target: str = Field(description="Destination node id or place id (poi:<slug>)")
    avoid_stairs: bool = False


class StepOut(BaseModel):
    node_id: str
    turn: Turn
    distance_m: float = Field(description="Walked after this step (estimate indoors)")
    bearing_deg: float = Field(description="Compass bearing outdoors; 0 indoors")
    text_tr: str
    text_en: str
    indoor: bool = Field(
        default=False,
        description="Inside a building: no compass, the distance is an estimate",
    )
    building: str | None = Field(
        default=None, description="Block the step is in, enters or leaves"
    )
    floor: int | None = Field(
        default=None, description="Storey at the step's spot (0 = ground)"
    )
    floors: int = Field(
        default=0, description="Storeys climbed (+) or descended (-) by stairs"
    )
    place: LocalizedText | None = Field(
        default=None, description="Indoor spot walked to (or started at)"
    )


class RouteResponse(BaseModel):
    node_ids: list[str]
    length_m: float
    duration_s: float
    coordinates: list[tuple[float, float]] = Field(
        description=(
            "[lng, lat] per node; indoor spots repeat their entrance's position: "
            "draw `parts`, not this"
        )
    )
    parts: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        description=(
            "[lng, lat] runs the map can draw: measured nodes joined by walks "
            "outside (the line breaks at indoor spots and passages)"
        ),
    )
    steps: list[StepOut]
    approximate: bool = Field(
        default=False,
        description="Length and duration include estimated indoor stretches",
    )


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
