import asyncio
from typing import Any

import httpx
import pytest

from amap_api.weather import WeatherService, WeatherUnavailableError

PAYLOAD: dict[str, Any] = {
    "current": {
        "time": "2026-10-06T13:00",
        "temperature_2m": 21.4,
        "weather_code": 61,
        "cloud_cover": 88,
        "precipitation": 0.6,
        "wind_speed_10m": 14.0,
        "wind_direction_10m": 220,
        "visibility": 9000,
        "is_day": 1,
    }
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _service(handler: Any, clock: FakeClock) -> tuple[WeatherService, list[int]]:
    calls: list[int] = []

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting))
    return WeatherService(client, ttl_s=600, clock=clock), calls


def test_weather_current_parses_open_meteo_payload() -> None:
    service, _ = _service(lambda _r: httpx.Response(200, json=PAYLOAD), FakeClock())
    weather = asyncio.run(service.current())
    assert weather.weather_code == 61 and weather.is_day is True, weather
    assert "Open-Meteo" in weather.attribution, weather.attribution


def test_weather_current_cached_within_ttl() -> None:
    clock = FakeClock()
    service, calls = _service(lambda _r: httpx.Response(200, json=PAYLOAD), clock)
    asyncio.run(service.current())
    clock.now = 599
    asyncio.run(service.current())
    assert len(calls) == 1, f"Expected one upstream call, got {len(calls)}"


def test_weather_current_serves_stale_on_upstream_error() -> None:
    clock = FakeClock()
    responses = iter([httpx.Response(200, json=PAYLOAD), httpx.Response(500)])
    service, _ = _service(lambda _r: next(responses), clock)
    asyncio.run(service.current())
    clock.now = 601
    weather = asyncio.run(service.current())
    assert weather.stale is True, "Cached data must be marked stale"


def test_weather_current_without_cache_raises_unavailable() -> None:
    service, _ = _service(lambda _r: httpx.Response(503), FakeClock())
    with pytest.raises(WeatherUnavailableError):
        asyncio.run(service.current())
