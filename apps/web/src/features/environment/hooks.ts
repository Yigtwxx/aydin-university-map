'use client';

import { useQuery } from '@tanstack/react-query';
import { getTimes } from 'suncalc';
import { useEffect, useMemo, useState } from 'react';

import { CAMPUS_LAT, CAMPUS_LNG } from '@/features/campus/constants';
import { api } from '@/lib/api/client';

import { type Sun, sunAt } from './sun';
import type { Weather } from './weather';

const WEATHER_REFRESH_MS = 10 * 60 * 1000;

/** The current time, re-rendered on every whole minute (or `stepMs`). */
export function useNow(stepMs = 60_000): Date {
  // Rounded to the step so the server render and hydration agree.
  const [now, setNow] = useState(() => roundDown(new Date(), stepMs));
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      // Align to the step boundary so the clock flips with the system clock.
      const wait = stepMs - (Date.now() % stepMs) + 20;
      timer = setTimeout(() => {
        setNow(roundDown(new Date(), stepMs));
        schedule();
      }, wait);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [stepMs]);
  return now;
}

function roundDown(date: Date, stepMs: number): Date {
  return new Date(Math.floor(date.getTime() / stepMs) * stepMs);
}

export function useWeather() {
  return useQuery<Weather>({
    queryKey: ['weather'],
    queryFn: async () => {
      const { data, error } = await api.GET('/weather');
      if (error || !data) throw new Error('weather unavailable');
      return data;
    },
    refetchInterval: WEATHER_REFRESH_MS,
    staleTime: WEATHER_REFRESH_MS,
    retry: 1,
  });
}

export type SkyPhase = 'day' | 'golden' | 'twilight' | 'night';

export interface Sky {
  sun: Sun;
  phase: SkyPhase;
  sunrise?: Date;
  sunset?: Date;
}

const DEG = Math.PI / 180;
/** Europe/Istanbul has stayed on UTC+3 all year since 2016. */
const ISTANBUL_UTC_OFFSET_MIN = 180;

export function phaseOf(altitude: number): SkyPhase {
  if (altitude > 8 * DEG) return 'day';
  if (altitude > -1 * DEG) return 'golden';
  if (altitude > -8 * DEG) return 'twilight';
  return 'night';
}

/** Sun position, phase and today's sunrise/sunset over the campus at `date`. */
export function useSky(date: Date): Sky {
  return useMemo(() => {
    const sun = sunAt(date);
    const times = getTimes(
      date,
      CAMPUS_LAT,
      CAMPUS_LNG,
      0,
      ISTANBUL_UTC_OFFSET_MIN,
    );
    return {
      sun,
      phase: phaseOf(sun.altitude),
      sunrise: times.sunrise ?? undefined,
      sunset: times.sunset ?? undefined,
    };
  }, [date]);
}

/** Mirrors the sky on <html data-theme>, so panels follow day and night. */
export function useThemeFromSky(phase: SkyPhase) {
  useEffect(() => {
    const night = phase === 'night' || phase === 'twilight';
    document.documentElement.dataset.theme = night ? 'night' : 'day';
  }, [phase]);
}
