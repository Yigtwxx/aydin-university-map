'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback } from 'react';

import { compassIndex } from '@/features/campus/coords';
import type { RouteStep } from '@/features/campus/queries';
import type { Locale } from '@/lib/format';

/** Steps the map cannot place: their distance is an estimate, no compass. */
export function isIndoorStep(step: RouteStep): boolean {
  return step.indoor || step.turn === 'enter';
}

/**
 * The distance worth showing for a step, if any: measured outside; inside
 * only a passage's (at least the line between its two doors), marked "≈".
 */
export function stepDistance(
  step: RouteStep,
  format: (metres: number) => string,
  approx: (distance: string) => string,
): string | undefined {
  if (step.distance_m <= 0) return undefined;
  if (!isIndoorStep(step)) return format(step.distance_m);
  return step.turn === 'through' ? approx(format(step.distance_m)) : undefined;
}

/**
 * The visitor's text for a route step (the directions list and the 360° walk
 * say the same). Outdoors: turns and compass; indoors: what to do.
 */
export function useStepText(): (
  step: RouteStep,
  destination: string,
) => string {
  const turns = useTranslations('Turns');
  const compass = useTranslations('Compass');
  const locale = useLocale() as Locale;
  return useCallback(
    (step, destination) => {
      const tag = locale === 'tr' ? 'tr-TR' : 'en-GB';
      const direction = () =>
        compass(String(compassIndex(step.bearing_deg)) as '0');
      const place = step.place
        ? locale === 'en'
          ? step.place.en
          : step.place.tr
        : '';
      switch (step.turn) {
        case 'arrive':
          return turns('arrive', { place: destination });
        case 'start':
          return step.indoor
            ? turns('startAt', { place })
            : turns('start', { direction: direction() });
        case 'enter':
          if (step.building) return turns('enter', { building: step.building });
          return place
            ? turns('enterNamed', { place })
            : turns('enterBuilding');
        case 'exit': {
          const way = direction().toLocaleLowerCase(tag);
          if (step.building)
            return turns('exit', { building: step.building, direction: way });
          return place
            ? turns('exitNamed', { place, direction: way })
            : turns('exitBuilding', { direction: way });
        }
        case 'through':
          if (step.building)
            return turns('through', { building: step.building });
          return place
            ? turns('throughNamed', { place })
            : turns('throughBuilding');
        case 'go_to':
          return turns('go_to', { place });
        case 'stairs_up':
        case 'stairs_down':
          return turns(step.turn, { count: Math.abs(step.floors) });
        default: {
          // A turn this page does not know yet (a newer API): its own text.
          const key = step.turn as 'straight';
          if (turns.has(key)) return turns(key);
          return locale === 'en' ? step.text_en : step.text_tr;
        }
      }
    },
    [turns, compass, locale],
  );
}
