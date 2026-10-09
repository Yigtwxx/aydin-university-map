'use client';

import { cn } from 'cn';
import { DoorOpen, Flame, Search } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { type Ref, useCallback, useId, useMemo, useRef, useState } from 'react';

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from '@/components/ui/combobox';
import { InputGroupAddon } from '@/components/ui/input-group';
import {
  type Place,
  usePlaceDirectory,
  usePlaces,
} from '@/features/campus/queries';
import { blockTone } from '@/features/map/blockTones';
import { useDebounced } from '@/hooks/useDebounced';
import type { Locale } from '@/lib/format';

import { whereText } from './indoor';
import { PanoThumb } from './PanoThumb';
import { CATEGORY_ICONS, PoiBadge } from './placeIcons';
import { categoryOf, popularOf, sceneOf } from './places';
import type { PlaceRef } from './store';

/** The API rejects longer queries (422). */
const MAX_QUERY_CHARS = 100;

interface Props {
  label: string;
  /** Name of the clear button, e.g. "Clear start". */
  clearLabel: string;
  placeholder: string;
  value?: PlaceRef;
  onChange: (place?: PlaceRef) => void;
  /**
   * `hero`: the panel's main "Where to?" field. `row`: one line of the
   * from/to card, where the card itself draws the field.
   */
  variant: 'hero' | 'row';
  inputRef?: Ref<HTMLInputElement>;
  /** The suggestions opened or closed. */
  onOpenChange?: (open: boolean) => void;
}

/** Server-side, Turkish-aware place search (the API folds ı/İ/ş/ğ…). */
export function PlaceSearch({
  label,
  clearLabel,
  placeholder,
  value,
  onChange,
  variant,
  inputRef,
  onOpenChange,
}: Props) {
  const id = useId();
  const locale = useLocale() as Locale;
  const t = useTranslations('Route');
  const [input, setInput] = useState('');
  const query = useDebounced(input, 150);
  const { data: results = [], isFetching, isError } = usePlaces(query);
  const directory = usePlaceDirectory();
  // An empty field suggests the popular places instead of an empty list.
  const suggesting = input.trim() === '';
  const suggestions = useMemo(
    () => popularOf(directory.data ?? []),
    [directory.data],
  );
  const shown = suggesting ? suggestions : results;

  const nameOf = (place: Place) =>
    locale === 'en' ? place.name_en : place.name_tr;
  const selected = useMemo<Place | undefined>(
    () =>
      value
        ? (shown.find((p) => p.id === value.id) ?? placeholderPlace(value))
        : undefined,
    [shown, value],
  );
  const items = useMemo(
    () =>
      selected && !shown.some((p) => p.id === selected.id)
        ? [...shown, selected]
        : shown,
    [shown, selected],
  );

  let emptyText: string | undefined;
  if (suggesting) {
    if (directory.isError) emptyText = t('apiDown');
    else if (directory.isPending) emptyText = t('searching');
  } else if (isError) emptyText = t('apiDown');
  // The debounce has not caught up with the typing yet.
  else if (isFetching || query.trim() !== input.trim())
    emptyText = t('searching');
  else emptyText = t('noResults');

  // Rooms share names across blocks ("Derslik"): say where each one is.
  // A business says what it is, and where when it is inside a block.
  const subtitleOf = (place: Place) => {
    if (place.category)
      return [
        t(`poi.${place.category}`),
        whereText(place, locale, place.name_tr, place.name_en),
      ]
        .filter(Boolean)
        .join(' · ');
    const category = categoryOf(place);
    if (category !== 'rooms') return t(`type.${category}`);
    const area = locale === 'en' ? place.area_en : place.area_tr;
    return (
      whereText(place, locale, place.name_tr, place.name_en) ??
      (area || t('type.rooms'))
    );
  };

  const hero = variant === 'hero';
  const field = useRef<HTMLDivElement>(null);
  // The list hangs below the field and spans the panel's content (the
  // closest `data-search-bounds`), so a from/to row gets the same wide list
  // as the main field. Read on every update: the field rides on the sheet.
  const anchor = useCallback(() => {
    const element = field.current;
    if (!element) return null;
    const bounds = element.closest('[data-search-bounds]') ?? element;
    return {
      contextElement: element,
      getBoundingClientRect: () => {
        const own = element.getBoundingClientRect();
        const wide = bounds.getBoundingClientRect();
        return DOMRect.fromRect({
          x: wide.left,
          y: own.top,
          width: wide.width,
          height: own.height,
        });
      },
    };
  }, []);

  return (
    <Combobox
      items={items}
      value={selected ?? null}
      filter={null}
      itemToStringLabel={(place: Place) => nameOf(place)}
      isItemEqualToValue={(a: Place, b: Place) => a.id === b.id}
      onValueChange={(place: Place | null) =>
        onChange(place ? { id: place.id, name: nameOf(place) } : undefined)
      }
      onInputValueChange={(next: string) => setInput(next)}
      onOpenChange={(open: boolean) => onOpenChange?.(open)}
    >
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div ref={field} className="w-full min-w-0">
        <ComboboxInput
          id={id}
          ref={inputRef}
          placeholder={placeholder}
          maxLength={MAX_QUERY_CHARS}
          showClear={Boolean(value)}
          clearLabel={clearLabel}
          showTrigger={false}
          className={cn(
            'w-full border-0 bg-transparent transition-[background-color,box-shadow] duration-150 ease-out-soft',
            // 16 px on touch screens stops iOS zooming into the field on focus.
            '[&_input]:text-[16px] [&_input]:placeholder:text-ink-muted md:[&_input]:text-base',
            hero
              ? [
                  'h-11 rounded-control bg-fill pl-1 hover:bg-fill-strong',
                  'has-[[data-slot=input-group-control]:focus-visible]:bg-stone-raised has-[[data-slot=input-group-control]:focus-visible]:shadow-thumb has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-route/45',
                ]
              : [
                  'h-10 rounded-[8px] pl-0 [&_input]:px-1',
                  'has-[[data-slot=input-group-control]:focus-visible]:ring-0',
                ],
            value ? '[&_input]:font-medium' : '',
          )}
        >
          {hero && (
            <InputGroupAddon align="inline-start" className="pr-0 pl-2.5">
              <Search className="size-4.5 text-ink-muted" aria-hidden />
            </InputGroupAddon>
          )}
        </ComboboxInput>
      </div>
      {/* Always below, never flipped: on the sheet the field starts near the
          bottom edge and rises with it, and a list flipped above it at peek
          stayed squeezed under the status pill. Its height is what is left
          below the field. */}
      <ComboboxContent
        anchor={anchor}
        side="bottom"
        sideOffset={hero ? 8 : 6}
        collisionAvoidance={{
          side: 'none',
          align: 'shift',
          fallbackAxisSide: 'none',
        }}
        collisionPadding={8}
        className="glass glass-solid rounded-card bg-(--glass-bg) p-1 ring-0"
      >
        <ComboboxEmpty className="py-3 text-sm text-ink-muted">
          {emptyText}
        </ComboboxEmpty>
        {suggesting && suggestions.length > 0 && (
          <p
            id={`${id}-popular`}
            className="flex items-center gap-1.5 px-2 pt-1.5 pb-1 text-xs font-medium text-ink-muted"
          >
            <Flame
              className="size-3.5 text-ochre"
              strokeWidth={2.25}
              aria-hidden
            />
            {t('popular')}
          </p>
        )}
        {/* Seven rows and a bit on desktop, so it reads as a list. */}
        <ComboboxList
          aria-labelledby={
            suggesting && suggestions.length > 0 ? `${id}-popular` : undefined
          }
          className="max-h-[min(23.5rem,calc(var(--available-height)-0.5rem))] p-0"
        >
          {(place: Place) => (
            <ComboboxItem
              key={place.id}
              value={place}
              className="gap-3 rounded-[10px] py-1.5 pr-8 pl-1.5 data-highlighted:bg-fill-strong"
            >
              <span className="relative shrink-0">
                <PanoThumb
                  scene={sceneOf(place)}
                  fallback={<PlaceGlyph place={place} />}
                  className="size-10 rounded-[8px]"
                />
                <PlaceBadge
                  place={place}
                  size="sm"
                  className="absolute -right-1 -bottom-1 ring-2 ring-stone-raised"
                />
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-md font-medium">
                  {nameOf(place)}
                </span>
                <span className="truncate text-xs text-ink-muted">
                  {subtitleOf(place)}
                </span>
              </span>
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

/**
 * A business's badge (like its map pin), a block letter in its block's tone
 * (like the map labels), or the category's icon.
 */
export function PlaceGlyph({
  place,
  className,
}: {
  place: Place;
  className?: string;
}) {
  if (place.category)
    return (
      <PoiBadge
        category={place.category}
        className={cn('size-8', className)}
        iconClassName="size-4.5"
      />
    );
  if (place.building)
    return (
      <span
        aria-hidden
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-[8px] text-sm font-semibold tracking-heading',
          blockTone(place.building),
          className,
        )}
      >
        {place.building}
      </span>
    );
  const category = categoryOf(place);
  const Icon = CATEGORY_ICONS[category === 'blocks' ? 'gates' : category];
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-muted',
        className,
      )}
    >
      <Icon className="size-4.5" strokeWidth={1.75} />
    </span>
  );
}

/**
 * The badge a place wears on the map, for a photo's corner: a business's pin
 * face, its block letter in the block's tone, or an ochre door for a campus
 * gate (the ochre of the map's entrance rims). Other places wear none.
 */
export function PlaceBadge({
  place,
  size,
  className,
}: {
  place: Place;
  /** `sm`: on a list row's thumbnail. `md`: on a photo tile. */
  size: 'sm' | 'md';
  className?: string;
}) {
  const sm = size === 'sm';
  if (place.category)
    return (
      <PoiBadge
        category={place.category}
        className={cn(sm ? 'size-4.5' : 'size-5.5', className)}
        iconClassName={sm ? 'size-2.5' : 'size-3'}
      />
    );
  if (place.building)
    return (
      <span
        aria-hidden
        className={cn(
          'flex items-center justify-center font-semibold',
          sm
            ? 'h-4.5 min-w-4.5 rounded-[5px] px-0.5 text-[10px]'
            : 'h-5.5 min-w-5.5 rounded-[6px] px-1 text-xs',
          blockTone(place.building),
          className,
        )}
      >
        {place.building}
      </span>
    );
  if (categoryOf(place) !== 'gates') return null;
  return (
    <span
      aria-hidden
      className={cn(
        'flex items-center justify-center rounded-full bg-ochre text-ochre-ink',
        sm ? 'size-4.5' : 'size-5.5',
        className,
      )}
    >
      <DoorOpen className={sm ? 'size-2.5' : 'size-3'} strokeWidth={2.25} />
    </span>
  );
}

/** Keeps a chosen place selectable while its search results are not loaded. */
function placeholderPlace(ref: PlaceRef): Place {
  return {
    id: ref.id,
    name_tr: ref.name,
    name_en: ref.name,
    kind: 'outdoor',
    building: null,
    node_ids: [ref.id],
    area_tr: '',
    area_en: '',
  };
}
