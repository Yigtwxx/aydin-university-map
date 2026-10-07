"""Street furniture and the ground's steps: what the map draws at human scale.

Measured on the panoramas (sightings and the ground orthomosaic) and kept in
``configs/furniture.toml``; published as ``furniture.json`` next to the other
map assets. Coordinates are local metres (east, north) from the campus origin;
heights are metres above the local ground datum the terraces use.

Stairs also matter to routing: an outdoor walking edge that crosses a flight
becomes a stairs edge, so step-free routes go round it (by a ramp, if any).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

FURNITURE_SCHEMA_VERSION = 1

Point = tuple[float, float]


class ItemKind(StrEnum):
    BENCH = "bench"
    TABLE = "table"
    CHAIR = "chair"
    UMBRELLA = "umbrella"
    PLANTER = "planter"
    BOLLARD = "bollard"
    BIN = "bin"
    LAMP = "lamp"
    BIKE_RACK = "bike_rack"


class Side(StrEnum):
    NONE = "none"
    LEFT = "left"  # seen walking up from the foot
    RIGHT = "right"
    BOTH = "both"


class Stairs(BaseModel):
    """A straight flight: centreline from its foot to its top."""

    model_config = ConfigDict(frozen=True)

    id: str
    foot: Point
    top: Point
    width_m: float = Field(gt=0.3, le=30.0)
    steps: int = Field(ge=1, le=200)
    base_z: float = Field(default=0.0, description="Ground height at the foot")
    rise_m: float = Field(gt=0.0, le=20.0, description="Height climbed in total")
    railings: Side = Side.NONE

    @property
    def run_m(self) -> float:
        return float(
            ((self.top[0] - self.foot[0]) ** 2 + (self.top[1] - self.foot[1]) ** 2)
            ** 0.5
        )

    @model_validator(mode="after")
    def _has_length(self) -> "Stairs":
        if self.run_m < 0.25:
            raise ValueError(f"stairs {self.id}: foot and top coincide")
        return self


class Ramp(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    foot: Point
    top: Point
    width_m: float = Field(gt=0.3, le=30.0)
    base_z: float = 0.0
    rise_m: float = Field(ge=0.0, le=10.0)
    railings: Side = Side.NONE


class Railing(BaseModel):
    """A free-standing rail (terrace edges, lane walls); stairs carry their own."""

    model_config = ConfigDict(frozen=True)

    id: str
    line: list[Point] = Field(min_length=2)
    height_m: float = Field(default=1.0, gt=0.2, le=3.0)
    base_z: float = 0.0


class Item(BaseModel):
    """One placed object: a bench, a planter, a lamp."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: ItemKind
    at: Point
    heading_deg: float = Field(default=0.0, ge=0.0, lt=360.0)
    length_m: float | None = Field(default=None, gt=0.0, le=20.0)
    base_z: float = 0.0


class SeatingGroup(BaseModel):
    """Café terrace tables and chairs: an area and how many seats, not a layout
    (chairs move every day)."""

    model_config = ConfigDict(frozen=True)

    id: str
    outline: list[Point] = Field(min_length=3)
    tables: int = Field(ge=1, le=200)
    seats_per_table: int = Field(default=4, ge=1, le=12)
    umbrellas: bool = False
    poi: str | None = Field(default=None, description="The café it belongs to")
    base_z: float = 0.0


class FurnitureCollection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = FURNITURE_SCHEMA_VERSION
    generated_at: datetime
    stairs: list[Stairs] = Field(default_factory=list[Stairs])
    ramps: list[Ramp] = Field(default_factory=list[Ramp])
    railings: list[Railing] = Field(default_factory=list[Railing])
    items: list[Item] = Field(default_factory=list[Item])
    seating: list[SeatingGroup] = Field(default_factory=list[SeatingGroup])

    @model_validator(mode="after")
    def _unique_ids(self) -> "FurnitureCollection":
        ids = [
            x.id
            for group in (
                self.stairs,
                self.ramps,
                self.railings,
                self.items,
                self.seating,
            )
            for x in group
        ]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate furniture ids: {dupes}")
        return self
