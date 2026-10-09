import { describe, expect, it } from 'vitest';

import type { Place } from '@/features/campus/queries';

import {
  blockEntrances,
  categoryOf,
  highlightsOf,
  pinnedPois,
  POPULAR_PLACE_IDS,
  popularOf,
  pinnedSpots,
  poiGroups,
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
  area_tr: '',
  area_en: '',
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
      cafe: 'eat',
      campus: 'outdoor',
    });
  });

  it('lists only categories that have places, in display order', () => {
    expect(presentCategories(directory)).toEqual([
      'blocks',
      'gates',
      'health',
      'library',
      'eat',
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

  it('suggests the popular places first, topped up with highlights', () => {
    const [gateId, canteenId] = POPULAR_PLACE_IDS;
    const popular = [
      place(canteenId!, 'Yemekhane', 'Canteen', { kind: 'indoor' }),
      place(gateId!, 'Kampüs Girişi', 'Campus Entrance'),
    ];
    expect(popularOf([...directory, ...popular], 4).map((p) => p.id)).toEqual([
      gateId,
      canteenId,
      'gate',
      'hosp',
    ]);
    expect(popularOf([], 4)).toEqual([]);
  });

  it('keeps a block garden out of the block keys', () => {
    const garden = place('tg', 'T Blok Bahçe', 'T Block Garden', {
      kind: 'outdoor',
      building: 'T',
    });
    expect(categoryOf(garden)).toBe('outdoor');
  });

  it('files rooms apart from their block, never as block keys', () => {
    const lab = place('lab', 'Anatomi Lab', 'Anatomy Lab', {
      kind: 'indoor',
      building: 'M',
      floor: 5,
    });
    expect(categoryOf(lab)).toBe('rooms');
    expect(blockEntrances([...directory, lab]).map((p) => p.id)).not.toContain(
      'lab',
    );
    expect(highlightsOf([lab, ...directory]).map((p) => p.id)).not.toContain(
      'lab',
    );
  });

  it('orders block entrances by letter', () => {
    expect(blockEntrances(directory).map((p) => p.building)).toEqual([
      'A',
      'B',
      'G-H',
    ]);
  });

  it('keeps one key per block: its main door, not a side door', () => {
    const side = place('t-side', 'T Blok Yan Giriş', 'T Block Side Entrance', {
      building: 'T',
    });
    const main = place('t', 'T Blok Giriş', 'T Block Entrance', {
      building: 'T',
    });
    const keys = blockEntrances([side, ...directory, main]);
    expect(keys.map((p) => p.id)).toEqual(['a', 'b', 'gh', 't']);
  });
});

const poi = (
  id: string,
  category: NonNullable<Place['category']>,
  extra: Partial<Place> = {},
): Place =>
  place(id, id, id, { kind: 'indoor', category, pin_enu: [0, 0], ...extra });

describe('business categories', () => {
  it('takes a business’s own category over names, kinds and blocks', () => {
    // Indoors, in a block, named like a café: still the health desk it is.
    const desk = poi('desk', 'health', {
      name_tr: 'Kafe Revir',
      building: 'D',
      kind: 'entrance',
    });
    expect(categoryOf(desk)).toBe('health');
    expect(categoryOf(poi('lab', 'service', { kind: 'indoor' }))).toBe(
      'services',
    );
    expect(blockEntrances([desk])).toEqual([]);
  });

  it('files every business category under a chip', () => {
    const chips = Object.fromEntries(
      (
        [
          'food',
          'cafe',
          'shop',
          'health',
          'library',
          'student_services',
          'atm',
          'sports',
          'parking',
          'service',
        ] as const
      ).map((c) => [c, categoryOf(poi(c, c))]),
    );
    expect(chips).toEqual({
      food: 'eat',
      cafe: 'eat',
      shop: 'shop',
      health: 'health',
      library: 'library',
      student_services: 'services',
      atm: 'services',
      sports: 'services',
      parking: 'services',
      service: 'services',
    });
  });

  it('lists business chips among the others, in display order', () => {
    expect(
      presentCategories([
        poi('atm', 'atm'),
        poi('bk', 'food'),
        poi('store', 'shop'),
        ...directory,
      ]),
    ).toEqual([
      'blocks',
      'gates',
      'health',
      'library',
      'eat',
      'shop',
      'services',
      'outdoor',
    ]);
  });
});

describe('business pins', () => {
  const places = [
    poi('bk', 'food', { pin_enu: [14, 35] }),
    poi('later', 'cafe', { pin_enu: null }),
    poi('fit', 'sports', { pin_enu: [-4.2, 34.2] }),
    poi('gym', 'sports', { pin_enu: [-4.2, 34.2] }),
    // Within 2 m of the gym's door: the same spot.
    poi('locker', 'service', { pin_enu: [-3, 35] }),
    poi('poi:atm', 'atm', { pin_enu: [-1, 37], node_ids: ['door'] }),
    place('a', 'A Blok Girişi', 'A Block Entrance', { building: 'A' }),
  ];

  it('pins only businesses with a pin', () => {
    expect(pinnedPois(places).map((p) => p.id)).toEqual([
      'bk',
      'fit',
      'gym',
      'locker',
      'poi:atm',
    ]);
  });

  it('shares one marker among the businesses at one spot', () => {
    expect(
      poiGroups(places).map((g) => [g.id, g.places.map((p) => p.id)]),
    ).toEqual([
      ['bk', ['bk']],
      ['fit', ['fit', 'gym', 'locker']],
      ['poi:atm', ['poi:atm']],
    ]);
  });

  it('shows a business’s own borrowed spots at its pin, never a neighbour’s', () => {
    const spots = pinnedSpots(
      [
        poi('bk', 'food', { pin_enu: [14, 35], node_ids: ['bk', 'bk2'] }),
        poi('poi:atm', 'atm', { pin_enu: [-3, 35], node_ids: ['door'] }),
      ],
      (id) => id !== 'bk2',
    );
    expect([...spots]).toEqual([['bk', [14, 35]]]);
  });
});
