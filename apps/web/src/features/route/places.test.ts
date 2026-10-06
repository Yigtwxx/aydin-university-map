import { describe, expect, it } from 'vitest';

import type { Place } from '@/features/campus/queries';

import {
  blockEntrances,
  categoryOf,
  highlightsOf,
  presentCategories,
} from './places';

const place = (
  id: string,
  name_tr: string,
  name_en: string,
  extra: Partial<Place> = {},
): Place => ({
  id,
  name_tr,
  name_en,
  kind: 'entrance',
  building: null,
  node_ids: [id],
  ...extra,
});

const directory: Place[] = [
  place('b', 'B Blok Giriş', 'B Block Entrance', { building: 'B' }),
  place('a', 'A Blok Girişi', 'A Block Entrance', { building: 'A' }),
  place('gh', 'G-H Blok Giriş', 'G-H Block Entrance', { building: 'G-H' }),
  place('side', 'Giriş', 'Entrance'),
  place('gate', 'Kampüs Girişi', 'Campus Entrance', {
    node_ids: ['gate', 'g2', 'g3'],
  }),
  place('er', 'Acil Giriş', 'Emergency Entrance'),
  place('hosp', 'Hastane Giriş', 'Hospital Entrance', {
    node_ids: ['hosp', 'h2'],
  }),
  place('lib', 'Kütüphane Giriş', 'Library Entrance'),
  place('cafe', 'Kampüs Marmaris Cafe', 'Campus Marmaris Cafe', {
    kind: 'outdoor',
  }),
  place('campus', 'Kampüs', 'Campus', { kind: 'outdoor' }),
];

describe('place categories', () => {
  it('derives categories from block letters, names and kinds', () => {
    const byId = Object.fromEntries(
      directory.map((p) => [p.id, categoryOf(p)]),
    );
    expect(byId).toMatchObject({
      a: 'blocks',
      side: 'gates',
      gate: 'gates',
      er: 'health',
      hosp: 'health',
      lib: 'library',
      cafe: 'cafe',
      campus: 'outdoor',
    });
  });

  it('lists only categories that have places, in display order', () => {
    expect(presentCategories(directory)).toEqual([
      'blocks',
      'gates',
      'health',
      'library',
      'cafe',
      'outdoor',
    ]);
    expect(presentCategories(directory.slice(0, 3))).toEqual(['blocks']);
  });

  it('highlights the best-covered place of each category, no blocks', () => {
    expect(highlightsOf(directory).map((p) => p.id)).toEqual([
      'gate',
      'hosp',
      'lib',
      'cafe',
    ]);
  });

  it('orders block entrances by letter', () => {
    expect(blockEntrances(directory).map((p) => p.building)).toEqual([
      'A',
      'B',
      'G-H',
    ]);
  });
});
