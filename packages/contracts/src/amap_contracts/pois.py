"""Points of interest: the businesses and services people look for on campus.

A POI enriches the place its panorama already is (Burger King's panorama is a
place named "Burger King"): it adds a category, a brand, aliases and a pin
where the storefront stands, measured by the panorama survey. A POI without a
panorama of its own (a cash machine; ``own_panorama = false``) becomes a place
with id ``poi:<slug>``, routed to the panorama ``node_id`` names.

Published as ``pois.json`` next to the other map assets; every reader must
treat a missing file as "no POIs".
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from amap_contracts.graph import LocalizedText

POI_SCHEMA_VERSION = 1
POI_PLACE_PREFIX = "poi:"


class PoiCategory(StrEnum):
    FOOD = "food"  # restaurants, fast food, canteens
    CAFE = "cafe"
    SHOP = "shop"  # stationery, campus store
    HEALTH = "health"  # infirmary, hospital desks, pharmacy
    LIBRARY = "library"
    STUDENT_SERVICES = "student_services"
    ATM = "atm"
    SPORTS = "sports"
    PARKING = "parking"
    SERVICE = "service"  # salons, labs open to the public, incubators


class PinSource(StrEnum):
    STOREFRONT = "storefront"  # measured by the panorama survey
    ENTRANCE = "entrance"  # indoors: the measured door of its building
    MANUAL = "manual"  # set by hand in configs/pois.toml


class VerifyStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"  # still in the tour, gone today: kept off the map
    UNKNOWN = "unknown"


class Verification(BaseModel):
    model_config = ConfigDict(frozen=True)

    checked: date
    status: VerifyStatus
    source: str | None = Field(default=None, description="URL or how it was checked")


class Poi(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: LocalizedText
    category: PoiCategory
    brand: str | None = None
    aliases: tuple[str, ...] = ()
    node_id: str | None = Field(
        default=None, description="Panorama of the business (route target)"
    )
    own_panorama: bool = Field(
        default=True,
        description=(
            "node_id is the business's own panorama (its place gets enriched); "
            "False: a nearby spot, the POI becomes a place of its own"
        ),
    )
    pin_enu: tuple[float, float] | None = Field(
        default=None,
        description="Storefront, local metres east/north; None until measured",
    )
    pin_source: PinSource | None = Field(
        default=None, description="What the pin marks (None without a pin)"
    )
    building: str | None = Field(default=None, description="Block code, e.g. 'D'")
    floor: int | None = None
    verified: Verification | None = None

    @property
    def place_id(self) -> str:
        return f"{POI_PLACE_PREFIX}{self.id}"

    @property
    def listed(self) -> bool:
        """Shown on the map: not known to be closed."""
        return self.verified is None or self.verified.status is not VerifyStatus.CLOSED


class PoiCollection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = POI_SCHEMA_VERSION
    generated_at: datetime
    pois: list[Poi]
