import { describe, expect, it } from 'vitest';

import type { Building, GraphNode } from '@/features/campus/types';

import {
  blockChips,
  blockCode,
  buildingCode,
  distanceToRing,
} from './blockChips';

const square = (e: number, n: number, size: number): [number, number][] => [
  [e, n],
  [e + size, n],
  [e + size, n + size],
  [e, n + size],
  [e, n],
];

const building = (
  id: string,
  name: string | null,
  outline: [number, number][],
): Building => ({ id, name, campus: true, height_m: 15, outline });

const door = (
  id: string,
  code: string,
  e: number,
  n: number,
  anchor?: string,
): GraphNode => ({
  id,
  kind: 'entrance',
  lat: 0,
  lng: 0,
  alt_m: 0,
  enu: [e, n, 0],
  heading_deg: 0,
  label: { tr: `${code} Blok Giriş`, en: `${code} Block Entrance` },
  area: { tr: '', en: '' },
  building: code,
  ...(anchor ? { anchor } : {}),
});

describe('buildingCode', () => {
  it('reads the letter from OSM names', () => {
    expect(buildingCode('İstanbul Aydın Üniversitesi A Binası')).toBe('A');
    expect(buildingCode('G-H Blok')).toBe('G-H');
    expect(buildingCode(null)).toBeUndefined();
  });
});

describe('blockCode', () => {
  const ring = square(0, 0, 10);
  it('prefers the registry code to the OSM name', () => {
    expect(
      blockCode({
        ...building('way/1', 'İstanbul Aydın Üniversitesi B Binası', ring),
        code: 'T',
      }),
    ).toBe('T');
    expect(blockCode({ ...building('way/1', null, ring), code: 'G-H' })).toBe(
      'G-H',
    );
  });

  it('falls back to the name, on campus only', () => {
    const named = building(
      'way/1',
      'İstanbul Aydın Üniversitesi A Binası',
      ring,
    );
    expect(blockCode(named)).toBe('A');
    expect(blockCode({ ...named, campus: false })).toBeUndefined();
  });

  it('gives no letter to a registry place that is not a lettered block', () => {
    expect(
      blockCode({
        ...building('way/1', 'İstanbul Aydın Üniversitesi Kütüphane', ring),
        code: 'KUTUPHANE',
      }),
    ).toBeUndefined();
  });
});

describe('distanceToRing', () => {
  it('is zero inside and the wall distance outside', () => {
    const ring = square(0, 0, 10).slice(0, 4);
    expect(distanceToRing([5, 5], ring)).toBe(0);
    expect(distanceToRing([13, 5], ring)).toBeCloseTo(3);
  });
});

describe('blockChips', () => {
  // OSM names one complex "B Binası"; the tour has the B and M doors on it.
  const complex = building(
    'way/1',
    'İstanbul Aydın Üniversitesi B Binası',
    square(0, 0, 80),
  );
  const other = building(
    'way/2',
    'İstanbul Aydın Üniversitesi N Binası',
    square(200, 0, 30),
  );

  it('puts each tour block over the wing its door opens into', () => {
    const chips = blockChips(
      [complex, other],
      [door('b', 'B', -2, 10), door('m', 'M', 82, 70)],
    );
    const codes = chips.map((c) => c.code);
    expect(codes).toEqual(['B', 'M', 'N']);
    const m = chips.find((c) => c.code === 'M')!;
    // Inside the complex, near the M door (world z is -north).
    expect(m.position[0]).toBeGreaterThan(60);
    expect(m.position[0]).toBeLessThan(80);
    expect(-m.position[2]).toBeGreaterThan(50);
  });

  it('keeps an OSM letter only when no tour block uses it', () => {
    const chips = blockChips([complex], [door('b', 'B', -2, 10)]);
    expect(chips.filter((c) => c.code === 'B')).toHaveLength(1);
    expect(chips[0]!.id).toBe('block-B');
  });

  it('moves a chip whose door stands at another block to its own building', () => {
    const a = building(
      'way/a',
      'İstanbul Aydın Üniversitesi A Binası',
      square(0, 0, 40),
    );
    const j = building(
      'way/j',
      'İstanbul Aydın Üniversitesi J Binası',
      square(100, 0, 20),
    );
    // The J door is posed at A's wall; A's own door stays where it is.
    const chips = blockChips(
      [a, j],
      [door('a', 'A', 10, -2), door('j', 'J', 30, -2)],
    );
    expect(chips.map((c) => c.code)).toEqual(['A', 'J']);
    const chipJ = chips.find((c) => c.code === 'J')!;
    expect(chipJ.position[0]).toBeCloseTo(110);
    expect(-chipJ.position[2]).toBeCloseTo(10);
    const chipA = chips.find((c) => c.code === 'A')!;
    expect(chipA.position[0]).toBeLessThan(40);
  });

  it('labels a block by its registry code when OSM has no name', () => {
    const t = { ...building('campus/T', null, square(300, 0, 30)), code: 'T' };
    const chips = blockChips([complex, t], [door('b', 'B', -2, 10)]);
    expect(chips.map((c) => c.code)).toEqual(['B', 'T']);
    expect(chips.find((c) => c.code === 'T')!.position[0]).toBeCloseTo(315);
  });

  it('ignores doors without a measured position', () => {
    const chips = blockChips([complex], [door('m', 'M', 82, 70, 'b')]);
    expect(chips.map((c) => c.code)).toEqual(['B']);
  });
});
