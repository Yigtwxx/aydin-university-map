'use client';

import { cn } from 'cn';
import {
  BookOpen,
  Coffee,
  Cross,
  DoorClosed,
  DoorOpen,
  type LucideIcon,
  Search,
  Trees,
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { type Ref, useId, useMemo, useRef, useState } from 'react';

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from '@/components/ui/combobox';
import { InputGroupAddon } from '@/components/ui/input-group';
import { type Place, usePlaces } from '@/features/campus/queries';
import { useDebounced } from '@/hooks/useDebounced';
import type { Locale } from '@/lib/format';

import { whereText } from './indoor';
import { PanoThumb } from './PanoThumb';
import { categoryOf, type PlaceCategory, sceneOf } from './places';
import type { PlaceRef } from './store';

interface Props {
  label: string;
  placeholder: string;
  value?: PlaceRef;
  onChange: (place?: PlaceRef) => void;
  /**
   * `hero`: the panel's main "Where to?" field. `row`: one line of the
   * from/to card, where the card itself draws the field.
   */
  variant: 'hero' | 'row';
  inputRef?: Ref<HTMLInputElement>;
}

/** Server-side, Turkish-aware place search (the API folds ı/İ/ş/ğ…). */
export function PlaceSearch({
  label,
  placeholder,
  value,
  onChange,
  variant,
  inputRef,
}: Props) {
  const id = useId();
  const locale = useLocale() as Locale;
  const t = useTranslations('Route');
  const [input, setInput] = useState('');
  const query = useDebounced(input, 150);
  const { data: results = [], isFetching, isError } = usePlaces(query);

  const nameOf = (place: Place) =>
    locale === 'en' ? place.name_en : place.name_tr;
  const selected = useMemo<Place | undefined>(
    () =>
      value
        ? (results.find((p) => p.id === value.id) ?? placeholderPlace(value))
        : undefined,
    [results, value],
  );
  const items = useMemo(
    () =>
      selected && !results.some((p) => p.id === selected.id)
        ? [...results, selected]
        : results,
    [results, selected],
  );

  let emptyText: string | undefined;
  if (isError) emptyText = t('apiDown');
  else if (isFetching) emptyText = t('searching');
  else if (query.trim()) emptyText = t('noResults');

  // Rooms share names across blocks ("Derslik"): say where each one is.
  const subtitleOf = (place: Place) => {
    const category = categoryOf(place);
    if (category !== 'rooms') return t(`type.${category}`);
    const area = locale === 'en' ? place.area_en : place.area_tr;
    return (
      whereText(place, locale, place.name_tr, place.name_en) ??
      (area || t('type.rooms'))
    );
  };

  const hero = variant === 'hero';
  // The list lines up with the whole field (icon included), not the bare input.
  const field = useRef<HTMLDivElement>(null);

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
    >
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div ref={field} className="w-full min-w-0">
        <ComboboxInput
          id={id}
          ref={inputRef}
          placeholder={placeholder}
          showClear={Boolean(value)}
          clearLabel={t('clear', { field: label })}
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
      <ComboboxContent
        anchor={field}
        sideOffset={hero ? 8 : 6}
        className="glass glass-solid min-w-72 rounded-card bg-(--glass-bg) p-1 ring-0"
      >
        <ComboboxEmpty className="py-3 text-sm text-ink-muted">
          {emptyText}
        </ComboboxEmpty>
        <ComboboxList className="p-0">
          {(place: Place) => (
            <ComboboxItem
              key={place.id}
              value={place}
              className="gap-3 rounded-[10px] py-1.5 pr-8 pl-1.5 data-highlighted:bg-fill-strong"
            >
              <PanoThumb
                scene={sceneOf(place)}
                fallback={<PlaceGlyph place={place} />}
                className="size-10 shrink-0 rounded-[8px]"
              />
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

export const CATEGORY_ICONS: Record<
  Exclude<PlaceCategory, 'blocks'>,
  LucideIcon
> = {
  gates: DoorOpen,
  health: Cross,
  library: BookOpen,
  cafe: Coffee,
  outdoor: Trees,
  rooms: DoorClosed,
};

/** Block letter on ochre (like the map labels), or the category's icon. */
export function PlaceGlyph({
  place,
  className,
}: {
  place: Place;
  className?: string;
}) {
  if (place.building)
    return (
      <span
        aria-hidden
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-ochre text-sm font-semibold tracking-heading text-ochre-ink',
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
