'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useId, useMemo, useState } from 'react';

import { FanMark } from '@/components/brand/FanMark';
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from '@/components/ui/combobox';
import { type Place, usePlaces } from '@/features/campus/queries';
import { useDebounced } from '@/hooks/useDebounced';

import type { PlaceRef } from './store';

interface Props {
  label: string;
  placeholder: string;
  value?: PlaceRef;
  onChange: (place?: PlaceRef) => void;
  marker: 'start' | 'end';
}

/** Server-side, Turkish-aware place search (the API folds ı/İ/ş/ğ…). */
export function PlaceSearch({
  label,
  placeholder,
  value,
  onChange,
  marker,
}: Props) {
  const id = useId();
  const locale = useLocale();
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
      <ComboboxInput
        id={id}
        placeholder={placeholder}
        showClear={Boolean(value)}
        clearLabel={t('clear', { field: label })}
        showTrigger={false}
        className={[
          'h-11 w-full rounded-xl border-0 bg-transparent pl-1 text-sm',
          'transition-colors duration-150 ease-out-soft hover:bg-accent',
          'has-[[data-slot=input-group-control]:focus-visible]:bg-stone-raised has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-route/40',
          marker === 'end' ? 'font-semibold' : '',
        ].join(' ')}
      />
      <ComboboxContent className="glass glass-thick rounded-2xl bg-transparent p-1 ring-0">
        <ComboboxEmpty>{emptyText}</ComboboxEmpty>
        <ComboboxList>
          {(place: Place) => (
            <ComboboxItem
              key={place.id}
              value={place}
              className="gap-3 rounded-xl py-2 pl-2"
            >
              <PlaceGlyph place={place} />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-semibold">{nameOf(place)}</span>
                <span className="text-xs text-ink-muted">
                  {describePlace(place, locale)}
                </span>
              </span>
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

/** Building letter for entrances, a fan for open campus areas. */
export function PlaceGlyph({ place }: { place: Place }) {
  if (place.building)
    return (
      <span
        aria-hidden
        className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-ochre/20 font-display text-md font-bold text-ink"
      >
        {place.building}
      </span>
    );
  return (
    <span
      aria-hidden
      className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-plane/15 text-plane"
    >
      <FanMark className="size-5" />
    </span>
  );
}

export function describePlace(place: Place, locale: string): string {
  const en = locale === 'en';
  if (place.kind === 'entrance' && place.building)
    return en
      ? `Block ${place.building} entrance`
      : `${place.building} Blok girişi`;
  if (place.kind === 'entrance') return en ? 'Entrance' : 'Giriş';
  if (place.kind === 'indoor') return en ? 'Indoors' : 'Bina içi';
  return en ? 'Open campus' : 'Açık alan';
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
  };
}
