import { describe, expect, it } from 'vitest';

import {
  formatDistance,
  formatDuration,
  formatFloor,
  sentenceCase,
} from './format';

describe('formatDistance', () => {
  it.each([
    [7.4, 'tr', '7 m'],
    [123, 'en', '125 m'],
    [1530, 'tr', '1,5 km'],
    [1530, 'en', '1.5 km'],
  ] as const)('formats %d m in %s as %s', (metres, locale, expected) => {
    expect(formatDistance(metres, locale)).toBe(expected);
  });
});

describe('formatDuration', () => {
  it('never shows less than one minute', () => {
    expect(formatDuration(12, 'en')).toBe('1 min');
  });

  it('uses the Turkish abbreviation', () => {
    expect(formatDuration(310, 'tr')).toBe('5 dk');
  });
});

describe('formatFloor', () => {
  it.each([
    [0, 'tr', 'zemin kat'],
    [5, 'tr', '5. kat'],
    [-1, 'tr', '\u22121. kat'],
    [0, 'en', 'ground floor'],
    [3, 'en', 'floor 3'],
    [-2, 'en', 'floor \u22122'],
  ] as const)('formats floor %d in %s as %s', (floor, locale, expected) => {
    expect(formatFloor(floor, locale)).toBe(expected);
  });
});

describe('sentenceCase', () => {
  it('capitalises with Turkish rules', () => {
    expect(sentenceCase('iç mekân', 'tr')).toBe('İç mekân');
    expect(sentenceCase('ground floor', 'en')).toBe('Ground floor');
  });
});
