'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useMemo } from 'react';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { enuToWorld } from '@/features/campus/coords';
import { type Place, useTerrain } from '@/features/campus/queries';
import { shownFloor, whereText } from '@/features/route/indoor';
import { PoiBadge } from '@/features/route/placeIcons';
import { type PinnedPoi, poiGroups } from '@/features/route/places';
import { formatFloor, type Locale } from '@/lib/format';

import type { ZoomTier } from './cameraStore';
import { MapAnchor } from './MapAnchor';

/**
 * Where a business is, for its pin's tooltip and the destination pin. Until
 * its storefront is measured the pin stands at its building's door, and says
 * so ("C Blok girişi · 4. kat"); otherwise its block and floor, if known.
 */
export function usePoiWhere(): (place: Place) => string | undefined {
  const t = useTranslations('Map');
  const locale = useLocale() as Locale;
  return useCallback(
    (place: Place) => {
      if (place.pin_source !== 'entrance')
        return whereText(place, locale, place.name_tr, place.name_en);
      const floor = shownFloor(place.floor, place.name_tr, place.name_en);
      return [
        place.building
          ? t('poiBlockDoor', { code: place.building })
          : t('poiDoor'),
        floor === undefined ? undefined : formatFloor(floor, locale),
      ]
        .filter(Boolean)
        .join(' · ');
    },
    [t, locale],
  );
}

/**
 * Businesses and services (Burger King, the library, the infirmary…) as
 * round glyphs in their category's colour, on a white marker whose tail
 * stands on the pin, so the door's own 360° dot stays in sight below it.
 * Businesses behind one door share one marker. Up close they are named;
 * further out only the glyphs stay, and of two markers that would touch
 * the nearer one stays (zooming in brings the other back); the campus
 * overview shows none. Behind a building a marker dims instead of hiding.
 * Each glyph is a button that makes its place the destination, as picking
 * it in the search does.
 */
export function PoiLayer({
  places,
  tier,
  quiet,
  hiddenId,
  onPick,
}: {
  /** The place directory; only businesses with a pin are drawn. */
  places: readonly Place[];
  tier: ZoomTier;
  /** While a route or a destination is shown: names give way to it. */
  quiet: boolean;
  /**
   * A place the destination pin already stands for; its marker steps aside
   * (with the businesses sharing its spot, which the pin would cover).
   */
  hiddenId?: string;
  onPick: (place: Place) => void;
}) {
  const locale = useLocale();
  const terrain = useTerrain();
  const groups = useMemo(() => poiGroups(places), [places]);
  const list = useMemo(
    () => new Intl.ListFormat(locale, { type: 'conjunction' }),
    [locale],
  );
  if (tier === 'far') return null;
  const near = tier === 'near';
  const nameOf = (place: Place) =>
    locale === 'en' ? place.name_en : place.name_tr;
  return groups.map((group) => {
    if (group.places.some((p) => p.id === hiddenId)) return null;
    const [east, north] = group.pin;
    return (
      <MapAnchor
        key={group.id}
        id={`pin-poi-${group.id}`}
        position={enuToWorld(east, north, terrain.heightAt(east, north) + 0.6)}
        layer={2}
      >
        {/* The tail's tip is the pin: up by the marker's height, left by
            half its width. The whole marker yields, so two never overlap. */}
        <div
          data-yield
          className="relative origin-bottom -translate-x-1/2 -translate-y-full animate-in transition-opacity duration-200 ease-out-soft fade-in-0 zoom-in-75"
        >
          <div className="relative flex flex-col items-center pb-1.5 drop-shadow-[0_2px_3px_rgb(15_23_36/0.32)]">
            <div data-marker className="flex rounded-full bg-white">
              {group.places.map((place) => (
                <PoiButton
                  key={place.id}
                  place={place}
                  name={nameOf(place)}
                  near={near}
                  onPick={onPick}
                />
              ))}
            </div>
            <span
              aria-hidden
              className="absolute bottom-0 left-1/2 -translate-x-1/2 border-x-[4.5px] border-t-[7px] border-x-transparent border-t-white"
            />
          </div>
          {near && !quiet && (
            <span
              aria-hidden
              data-label
              // Level with the glyphs (28 px up close).
              className="map-halo pointer-events-none absolute top-0 left-full ml-1 flex h-7 items-center text-xs font-semibold tracking-heading whitespace-nowrap text-ink transition-opacity duration-150"
            >
              {list.format(group.places.map(nameOf))}
            </span>
          )}
        </div>
      </MapAnchor>
    );
  });
}

/** One business on a marker: its glyph, a tooltip, and a 24 px+ target. */
function PoiButton({
  place,
  name,
  near,
  onPick,
}: {
  place: PinnedPoi;
  name: string;
  near: boolean;
  onPick: (place: Place) => void;
}) {
  const t = useTranslations();
  const where = usePoiWhere()(place);
  const category = t(`Route.poi.${place.category}`);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            onClick={() => onPick(place)}
            aria-label={
              where
                ? t('Map.poiAt', { name, category, where })
                : t('Map.poi', { name, category })
            }
            className="group pointer-events-auto rounded-full p-0.5"
          />
        }
      >
        <PoiBadge
          category={place.category}
          className={[
            'transition-transform duration-150 ease-out-soft group-hover:scale-110 group-focus-visible:scale-110',
            near ? 'size-6' : 'size-5',
          ].join(' ')}
          iconClassName={near ? 'size-3.5' : 'size-3'}
        />
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6}>
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold">{name}</span>
          <span className="opacity-70">
            {[category, where].filter(Boolean).join(' · ')}
          </span>
        </span>
      </TooltipContent>
    </Tooltip>
  );
}
