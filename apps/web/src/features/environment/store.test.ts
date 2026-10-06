import { describe, expect, it } from 'vitest';

import { atCampusHour, campusHour } from './store';

describe('atCampusHour', () => {
  it('moves to the given hour of the same İstanbul day', () => {
    // 14:09 in İstanbul (UTC+3).
    const now = new Date('2026-10-06T11:09:00Z');
    expect(atCampusHour(now, 21.5).toISOString()).toBe(
      '2026-10-06T18:30:00.000Z',
    );
  });

  it('keeps the İstanbul day even when UTC is still on the previous day', () => {
    // 01:30 on 7 October in İstanbul is 22:30 on 6 October in UTC.
    const now = new Date('2026-10-06T22:30:00Z');
    expect(atCampusHour(now, 8).toISOString()).toBe('2026-10-07T05:00:00.000Z');
  });
});

describe('campusHour', () => {
  it('returns İstanbul wall-clock hours', () => {
    expect(campusHour(new Date('2026-10-06T11:15:00Z'))).toBeCloseTo(14.25);
  });
});
