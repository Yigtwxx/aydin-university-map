'use client';

import { cn } from 'cn';
import { Building2 } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { type Place, usePlaceDirectory } from '@/features/campus/queries';

import { PanoThumb } from './PanoThumb';
import { CATEGORY_ICONS, PlaceGlyph } from './PlaceSearch';
import {
  blockEntrances,
  categoryOf,
  highlightsOf,
  type PlaceCategory,
  presentCategories,
  sceneOf,
} from './places';

interface Props {
  /** Places already chosen (start or destination); they are not offered. */
  exclude: (string | undefined)[];
  onPick: (place: Place, name: string) => void;
}

/**
 * What to pick before typing: category chips, photo tiles of the key places
 * and a keypad of block letters. A chip narrows everything to one category.
 */
export function PlaceBrowser({ exclude, onPick }: Props) {
  const t = useTranslations('Route');
  const locale = useLocale();
  const { data: directory = [], isError, isPending } = usePlaceDirectory();
  const [category, setCategory] = useState<PlaceCategory>();

  const places = useMemo(
    () => directory.filter((p) => !exclude.includes(p.id)),
    [directory, exclude],
  );
  const categories = useMemo(() => presentCategories(places), [places]);
  const nameOf = (place: Place) =>
    locale === 'en' ? place.name_en : place.name_tr;
  const pick = (place: Place) => onPick(place, nameOf(place));

  if (isError) return <p className="px-1 text-sm text-brick">{t('apiDown')}</p>;
  if (isPending) return <BrowserSkeleton />;

  const filtered = category
    ? places
        .filter((p) => categoryOf(p) === category)
        .sort((a, b) => nameOf(a).localeCompare(nameOf(b), locale))
    : [];

  return (
    <div className="flex flex-col gap-4">
      <div
        role="group"
        aria-label={t('categories')}
        ref={wheelToSideways}
        className="fade-x -mx-4 no-scrollbar flex gap-1.5 overflow-x-auto overscroll-x-contain px-4 py-0.5"
      >
        {categories.map((c) => {
          const Icon = c === 'blocks' ? Building2 : CATEGORY_ICONS[c];
          const pressed = category === c;
          return (
            <button
              key={c}
              type="button"
              aria-pressed={pressed}
              onClick={() => setCategory(pressed ? undefined : c)}
              className={cn(
                'flex h-8 shrink-0 items-center gap-1.5 rounded-full pr-3 pl-2.5 text-sm font-medium whitespace-nowrap',
                'transition-[background-color,color,box-shadow] duration-150 ease-out-soft',
                pressed
                  ? 'bg-ink text-stone-raised shadow-thumb'
                  : 'bg-fill text-ink hover:bg-fill-strong',
              )}
            >
              <Icon
                className={cn(
                  'size-3.5',
                  pressed ? 'text-stone-raised' : 'text-ink-muted',
                )}
                strokeWidth={2}
                aria-hidden
              />
              {t(`category.${c}`)}
            </button>
          );
        })}
      </div>

      {category ? (
        <TileGrid places={filtered} nameOf={nameOf} onPick={pick} />
      ) : (
        <>
          <section aria-labelledby="highlights-heading">
            <h3
              id="highlights-heading"
              className="mb-2 px-0.5 text-sm font-medium text-ink-muted"
            >
              {t('highlights')}
            </h3>
            <TileGrid
              places={highlightsOf(places)}
              nameOf={nameOf}
              onPick={pick}
            />
          </section>
          <BlockKeys places={blockEntrances(places)} onPick={pick} />
        </>
      )}
    </div>
  );
}

function TileGrid({
  places,
  nameOf,
  onPick,
}: {
  places: Place[];
  nameOf: (place: Place) => string;
  onPick: (place: Place) => void;
}) {
  return (
    <ul className="grid grid-cols-2 gap-x-2.5 gap-y-3">
      {places.map((place) => (
        <li key={place.id} className="min-w-0">
          <button
            type="button"
            onClick={() => onPick(place)}
            className="group flex w-full flex-col gap-1.5 rounded-card text-left focus-visible:outline-offset-4"
          >
            <PanoThumb
              scene={sceneOf(place)}
              fallback={<PlaceGlyph place={place} className="size-10" />}
              className="aspect-[16/10] w-full rounded-card group-hover:[&_img]:scale-[1.04]"
            >
              {place.building && (
                <span
                  aria-hidden
                  className="absolute bottom-1.5 left-1.5 flex h-5.5 min-w-5.5 items-center justify-center rounded-[6px] bg-ochre px-1 text-xs font-semibold text-ochre-ink shadow-thumb"
                >
                  {place.building}
                </span>
              )}
            </PanoThumb>
            <span className="truncate px-0.5 text-md font-medium tracking-heading">
              {nameOf(place)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Blocks are known by their letters on campus: one key per entrance. */
function BlockKeys({
  places,
  onPick,
}: {
  places: Place[];
  onPick: (place: Place) => void;
}) {
  const t = useTranslations('Route');
  const locale = useLocale();
  if (places.length === 0) return null;
  return (
    <section aria-labelledby="blocks-heading">
      <h3
        id="blocks-heading"
        className="mb-2 px-0.5 text-sm font-medium text-ink-muted"
      >
        {t('blocks')}
      </h3>
      <ul className="grid grid-cols-5 gap-1.5">
        {places.map((place) => {
          const name = locale === 'en' ? place.name_en : place.name_tr;
          return (
            <li key={place.id}>
              <button
                type="button"
                onClick={() => onPick(place)}
                aria-label={name}
                title={name}
                className="group flex h-10 w-full items-center justify-center rounded-control bg-fill transition-colors duration-150 ease-out-soft hover:bg-fill-strong"
              >
                {/* The same badge the block wears on the map. */}
                <span className="flex h-6 min-w-6 items-center justify-center rounded-[7px] bg-ochre px-1 text-xs font-semibold text-ochre-ink shadow-thumb transition-transform duration-150 ease-out-soft group-hover:scale-110">
                  {place.building}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function BrowserSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <div className="flex gap-1.5">
        {[64, 72, 56, 80].map((w) => (
          <span
            key={w}
            className="h-8 animate-shimmer rounded-full bg-fill"
            style={{ width: w }}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="aspect-[16/10] animate-shimmer rounded-card bg-fill"
          />
        ))}
      </div>
    </div>
  );
}

/**
 * A mouse wheel only scrolls vertically; over the chip row it slides the
 * chips instead (and keeps the panel still). Trackpads already scroll
 * sideways and pass through untouched.
 */
function wheelToSideways(row: HTMLDivElement | null) {
  if (!row) return;
  const onWheel = (event: WheelEvent) => {
    if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    const max = row.scrollWidth - row.clientWidth;
    if (max <= 0) return;
    const next = Math.min(max, Math.max(0, row.scrollLeft + event.deltaY));
    if (next === row.scrollLeft) return;
    event.preventDefault();
    row.scrollLeft = next;
  };
  row.addEventListener('wheel', onWheel, { passive: false });
  return () => row.removeEventListener('wheel', onWheel);
}
