"""How a campus block looks from the outside: the facade recipe the map draws.

Written per block in ``configs/campus.toml`` from what the panoramas show
(colours sampled with ``amap look sample``, window rhythm counted on the
walls) and published inside ``buildings.json`` as the building's ``facade``.
Colours are sRGB hex; lengths are metres.

A recipe describes the typical wall; ``walls`` override it on the sides that
differ (a glass front facing the street), picked by the compass direction a
wall faces. ``features`` are the few shapes that make a block recognisable:
E Blok's blue-and-white drum, A Blok's entrance tower, a door canopy.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

HexColour = str
_HEX = r"^#[0-9a-fA-F]{6}$"


class WindowRecipe(StrEnum):
    PUNCHED = "punched"  # separate windows in a solid wall
    RIBBON = "ribbon"  # continuous horizontal bands
    CURTAIN = "curtain"  # a glass wall
    BLANK = "blank"  # no windows (a blind side wall)


class GroundFloor(StrEnum):
    SAME = "same"  # like the floors above
    GLAZED = "glazed"  # shop fronts / lobby glass
    SOLID = "solid"
    ARCADE = "arcade"  # columns with a recessed glass line


class Wall(BaseModel):
    """A side of the block that differs from the recipe."""

    model_config = ConfigDict(frozen=True)

    facing_deg: float = Field(ge=0.0, lt=360.0, description="Compass direction out")
    tolerance_deg: float = Field(default=30.0, gt=0.0, le=90.0)
    windows: WindowRecipe | None = None
    wall: HexColour | None = Field(default=None, pattern=_HEX)
    ground: GroundFloor | None = None


class FeatureKind(StrEnum):
    DRUM = "drum"  # a cylinder (stair tower, rotunda)
    TOWER = "tower"  # a box rising above the roof
    CANOPY = "canopy"  # a flat roof over a door
    PORTAL = "portal"  # a framed door
    BAND = "band"  # a coloured stripe round the block at a height


class Feature(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: FeatureKind
    at: tuple[float, float] | None = Field(
        default=None, description="Centre, local metres (not for bands)"
    )
    width_m: float = Field(default=3.0, gt=0.0, le=60.0)
    depth_m: float = Field(default=3.0, gt=0.0, le=60.0)
    height_m: float = Field(default=3.0, gt=0.0, le=80.0)
    base_m: float = Field(default=0.0, ge=0.0, le=80.0)
    facing_deg: float = Field(default=0.0, ge=0.0, lt=360.0)
    colour: HexColour = Field(default="#ffffff", pattern=_HEX)
    accent: HexColour | None = Field(default=None, pattern=_HEX)


class Facade(BaseModel):
    model_config = ConfigDict(frozen=True)

    wall: HexColour = Field(pattern=_HEX)
    plinth: HexColour | None = Field(
        default=None, pattern=_HEX, description="Ground-floor band, if different"
    )
    trim: HexColour = Field(default="#f4f1ea", pattern=_HEX)
    glass: HexColour = Field(default="#3b4f5e", pattern=_HEX)
    roof: HexColour | None = Field(default=None, pattern=_HEX)
    windows: WindowRecipe = WindowRecipe.PUNCHED
    bay_m: float = Field(default=3.4, ge=0.8, le=12.0, description="Window spacing")
    window_width: float = Field(
        default=0.45, gt=0.0, le=1.0, description="Share of bay"
    )
    window_height: float = Field(
        default=0.5, gt=0.0, le=1.0, description="Share of storey"
    )
    storey_m: float = Field(default=3.4, ge=2.4, le=8.0)
    ground: GroundFloor = GroundFloor.SAME
    ground_m: float = Field(
        default=4.0, ge=2.4, le=10.0, description="Ground floor height"
    )
    walls: tuple[Wall, ...] = ()
    features: tuple[Feature, ...] = ()
