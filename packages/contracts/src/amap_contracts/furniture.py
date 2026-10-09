"""Street furniture and the ground's steps: what the map draws at human scale.

Measured on the panoramas (sightings and the ground orthomosaic) and kept in
``configs/furniture.toml``; published as ``furniture.json`` next to the other
map assets. Coordinates are local metres (east, north) from the campus origin;
heights are metres above the local ground datum the terraces use.

Heights. Terraces give the ground's height (``z_m``). A flight or ramp
stands outside the terraces it joins, rising from ``base_z`` at its foot to
``base_z + rise_m`` at its top. Items and café groups with ``base_z = 0``
stand on whatever ground is there (the renderer looks it up). A free-standing
railing uses ``base_z`` exactly as given, so one on a terrace edge carries the
terrace's height.

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
    FLAGPOLE = "flagpole"  # a mast with its flag; length_m = mast height
    BOOTH = "booth"  # a security or ticket cabin
    KIOSK = "kiosk"  # a small coloured stand: book swap, info, vending
    EMBLEM = "emblem"  # the university seal on a round plinth; length_m = diameter
    LETTERS = "letters"  # free-standing block letters (IAU); length_m = their width
    TOPIARY = "topiary"  # a shrub clipped to a ball
    STATUE = "statue"  # a life-size bronze animal; heading = where its head points
    SIGN = "sign"  # a free-standing board or totem; length_m = its width
    STAND = "stand"  # a red info lectern: an angled board on a post
    HEDGE = "hedge"  # a clipped box hedge; length_m along it, heading across


class Side(StrEnum):
    NONE = "none"
    LEFT = "left"  # seen walking up from the foot
    RIGHT = "right"
    BOTH = "both"


class RailingStyle(StrEnum):
    STEEL = "steel"  # posts with a top and a mid rail
    FENCE = "fence"  # the campus boundary: brick plinth and piers, iron bars


class Edge(StrEnum):
    WALL = "wall"  # a retaining wall down to the lower ground
    SLOPE = "slope"  # a grassy bank
    KERB = "kerb"  # a step of a kerb's height


class Terrace(BaseModel):
    """A level area raised above (or sunk below) the street datum (z = 0).

    The campus square stands about 1.5 m above the lane along D Blok; each
    terrace is one level polygon, its sides drawn as ``edge``.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    outline: list[Point] = Field(min_length=3)
    z_m: float = Field(ge=-10.0, le=20.0, description="Top above the street datum")
    edge: Edge = Edge.WALL
    bank_m: float | None = Field(
        default=None,
        gt=0.0,
        le=20.0,
        description=(
            "Width of a 'slope' edge's bank, out from the outline; None lets the "
            "renderer size it from the climb"
        ),
    )


class StairCorners(BaseModel):
    """A flight's drawn outline when it is not a rectangle.

    Left and right as seen walking up. Tiers that fan round a curve are cut
    to meet their neighbours and the rim they climb to, with no wedge left
    open between them.
    """

    model_config = ConfigDict(frozen=True)

    foot_left: Point
    foot_right: Point
    top_left: Point
    top_right: Point


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


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
    corners: StairCorners | None = Field(
        default=None,
        description=(
            "Drawn outline when the flight is not a rectangle; foot, top and "
            "width stay the walking line"
        ),
    )

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

    @model_validator(mode="after")
    def _corners_wind_upwards(self) -> "Stairs":
        """The corners make a convex quad, left corners left of the climb."""
        c = self.corners
        if c is None:
            return self
        quad = [c.foot_right, c.top_right, c.top_left, c.foot_left]
        turns = [_cross(quad[i - 2], quad[i - 1], quad[i]) for i in range(4)]
        if not all(t > 0 for t in turns):
            raise ValueError(
                f"stairs {self.id}: corners must run foot_right, top_right, "
                "top_left, foot_left anticlockwise (left is left walking up)"
            )
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


class Walkway(BaseModel):
    """A raised walk over lower ground: a slab on columns, a footbridge.

    The ground under it keeps its own terraces, walls and fence; ``spots``
    are the panoramas taken up on it. Routing only (the blocks' canopy
    features draw it): a walk on it ignores what is below, and reaches the
    ground by a flight or ramp whose top meets it.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    outline: list[Point] = Field(min_length=3)
    z_m: float = Field(ge=-10.0, le=20.0, description="Floor above the street datum")
    holes: list[list[Point]] = Field(
        default_factory=list[list[Point]],
        description="What stands on it and is walked round: a lift tower",
    )
    spots: list[str] = Field(
        default_factory=list[str], description="Panoramas taken up on it"
    )


class Railing(BaseModel):
    """A free-standing rail (terrace edges, lane walls); stairs carry their own."""

    model_config = ConfigDict(frozen=True)

    id: str
    line: list[Point] = Field(min_length=2)
    height_m: float = Field(default=1.0, gt=0.2, le=3.0)
    base_z: float = 0.0
    style: RailingStyle = RailingStyle.STEEL


class Item(BaseModel):
    """One placed object: a bench, a planter, a lamp.

    ``heading_deg`` is the compass bearing its front faces (where a person on
    a bench looks); ``length_m`` runs across it.
    """

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
    terraces: list[Terrace] = Field(default_factory=list[Terrace])
    stairs: list[Stairs] = Field(default_factory=list[Stairs])
    ramps: list[Ramp] = Field(default_factory=list[Ramp])
    railings: list[Railing] = Field(default_factory=list[Railing])
    items: list[Item] = Field(default_factory=list[Item])
    seating: list[SeatingGroup] = Field(default_factory=list[SeatingGroup])
    walkways: list[Walkway] = Field(default_factory=list[Walkway])

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
                self.walkways,
            )
            for x in group
        ]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate furniture ids: {dupes}")
        return self
