"""Geographic constants for the Florya campus."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned WGS84 bounding box (degrees)."""

    south: float
    west: float
    north: float
    east: float

    def contains(self, lat: float, lng: float) -> bool:
        return self.south < lat < self.north and self.west < lng < self.east


# Local ENU origin used by every metric coordinate in the project.
CAMPUS_ORIGIN_LAT = 40.9915
CAMPUS_ORIGIN_LNG = 28.7971

# Generous box around the Florya (Beşyol) campus; separates it from the other
# campuses that share the same 360 tour.
FLORYA_BBOX = BBox(south=40.985, west=28.790, north=40.996, east=28.800)

# UTM zone 35N covers İstanbul; used for metric georeferencing.
METRIC_CRS = "EPSG:32635"
