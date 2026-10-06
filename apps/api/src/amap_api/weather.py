"""Current campus weather from Open-Meteo (CC BY 4.0) with a TTL cache.

On upstream errors the last good observation is served (marked ``stale``), so
the 3D scene keeps its weather instead of flickering back to defaults.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import httpx

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
_CURRENT = (
    "temperature_2m,weather_code,cloud_cover,precipitation,"
    "wind_speed_10m,wind_direction_10m,visibility,is_day"
)


@dataclass(frozen=True, slots=True)
class Weather:
    observed_at: str
    temperature_c: float
    weather_code: int
    cloud_cover_pct: float
    precipitation_mm: float
    wind_speed_kmh: float
    wind_direction_deg: float
    visibility_m: float
    is_day: bool
    stale: bool = False
    attribution: str = ATTRIBUTION


class WeatherUnavailableError(RuntimeError):
    """Open-Meteo failed and no earlier observation is cached."""


def parse_current(payload: dict[str, Any]) -> Weather:
    current = payload["current"]
    return Weather(
        observed_at=str(current["time"]),
        temperature_c=float(current["temperature_2m"]),
        weather_code=int(current["weather_code"]),
        cloud_cover_pct=float(current["cloud_cover"]),
        precipitation_mm=float(current["precipitation"]),
        wind_speed_kmh=float(current["wind_speed_10m"]),
        wind_direction_deg=float(current["wind_direction_10m"]),
        visibility_m=float(current.get("visibility") or 0.0),
        is_day=bool(current["is_day"]),
    )


class WeatherService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        ttl_s: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl_s = ttl_s
        self._clock = clock
        self._cached: Weather | None = None
        self._fetched_at = -float("inf")

    async def current(self) -> Weather:
        if self._cached is not None and self._clock() - self._fetched_at < self._ttl_s:
            return self._cached
        try:
            response = await self._client.get(
                OPEN_METEO_URL,
                params={
                    "latitude": CAMPUS_ORIGIN_LAT,
                    "longitude": CAMPUS_ORIGIN_LNG,
                    "current": _CURRENT,
                    "timezone": "Europe/Istanbul",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            weather = parse_current(response.json())
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            if self._cached is None:
                raise WeatherUnavailableError("weather provider unavailable") from exc
            return replace(self._cached, stale=True)
        self._cached, self._fetched_at = weather, self._clock()
        return weather
