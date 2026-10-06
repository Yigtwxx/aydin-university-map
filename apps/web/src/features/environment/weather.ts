import type { components } from '@/lib/api/schema';

export type Weather = components['schemas']['WeatherOut'];

/** What the sky looks like, coarse enough to drive icons, copy and the scene. */
export type Condition =
  | 'clear'
  | 'mainlyClear'
  | 'partlyCloudy'
  | 'overcast'
  | 'fog'
  | 'drizzle'
  | 'rain'
  | 'showers'
  | 'snow'
  | 'storm';

/** WMO weather interpretation codes (Open-Meteo `weather_code`). */
export function conditionOf(code: number): Condition {
  if (code === 0) return 'clear';
  if (code === 1) return 'mainlyClear';
  if (code === 2) return 'partlyCloudy';
  if (code === 3) return 'overcast';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 57) return 'drizzle';
  if (code >= 61 && code <= 67) return 'rain';
  if (code >= 80 && code <= 82) return 'showers';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'storm';
  return 'partlyCloudy';
}

/** Precipitation the scene should render, if any. */
export function precipitationOf(
  condition: Condition,
): 'rain' | 'snow' | undefined {
  if (condition === 'snow') return 'snow';
  if (
    condition === 'drizzle' ||
    condition === 'rain' ||
    condition === 'showers' ||
    condition === 'storm'
  )
    return 'rain';
  return undefined;
}

const COMPASS_POINTS = 8;

/** Index into the 8-point compass of the direction the wind blows *from*. */
export function windFromIndex(directionDeg: number): number {
  const sector = 360 / COMPASS_POINTS;
  return (
    Math.round((((directionDeg % 360) + 360) % 360) / sector) % COMPASS_POINTS
  );
}
