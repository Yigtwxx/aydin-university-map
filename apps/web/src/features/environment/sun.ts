import { getPosition, getTimes } from 'suncalc';

import { CAMPUS_LAT, CAMPUS_LNG } from '@/features/campus/constants';

export interface Sun {
  /** Unit vector towards the sun in local ENU (east, north, up). */
  direction: [number, number, number];
  /** Radians above the horizon (negative at night). */
  altitude: number;
  /** Compass bearing of the sun, degrees clockwise from north. */
  bearingDeg: number;
}

const RAD = Math.PI / 180;

/**
 * Sun position over the Florya campus at ``date`` (suncalc, no network).
 * suncalc 2.x returns degrees, azimuth clockwise from north (a compass bearing).
 */
export function sunAt(date: Date, lat = CAMPUS_LAT, lng = CAMPUS_LNG): Sun {
  const { azimuth, altitude: altitudeDeg } = getPosition(date, lat, lng);
  const altitude = altitudeDeg * RAD;
  const bearing = azimuth * RAD;
  const flat = Math.cos(altitude);
  return {
    direction: [
      Math.sin(bearing) * flat,
      Math.cos(bearing) * flat,
      Math.sin(altitude),
    ],
    altitude,
    bearingDeg: ((azimuth % 360) + 360) % 360,
  };
}

export interface SunEvent {
  kind: 'sunrise' | 'sunset';
  at: Date;
}

const DAY_MS = 24 * 60 * 60 * 1000;
/** Europe/Istanbul has stayed on UTC+3 all year since 2016. */
const ISTANBUL_UTC_OFFSET_MIN = 180;

/**
 * The next sunrise or sunset after `date` over the campus: the sunrise while
 * the sun is down (after midnight as well as after dusk, then tomorrow's),
 * the sunset while it is up. Comparing against today's sunset alone showed
 * "Sunset 18:37" at 00:59.
 */
export function nextSunEvent(
  date: Date,
  lat = CAMPUS_LAT,
  lng = CAMPUS_LNG,
): SunEvent | undefined {
  for (const day of [0, 1]) {
    const times = getTimes(
      new Date(date.getTime() + day * DAY_MS),
      lat,
      lng,
      0,
      ISTANBUL_UTC_OFFSET_MIN,
    );
    const events: SunEvent[] = [];
    if (times.sunrise) events.push({ kind: 'sunrise', at: times.sunrise });
    if (times.sunset) events.push({ kind: 'sunset', at: times.sunset });
    const next = events
      .filter((event) => event.at > date)
      .sort((a, b) => a.at.getTime() - b.at.getTime())[0];
    if (next) return next;
  }
  return undefined;
}
