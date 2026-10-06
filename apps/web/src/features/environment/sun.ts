import { getPosition } from 'suncalc';

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
