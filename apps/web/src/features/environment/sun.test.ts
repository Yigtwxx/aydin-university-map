import { describe, expect, it } from 'vitest';

import { nextSunEvent, sunAt } from './sun';

describe('sunAt', () => {
  it('stands high in the southern sky at summer noon in İstanbul', () => {
    const sun = sunAt(new Date('2026-06-21T10:00:00Z')); // 13:00 Europe/Istanbul
    expect(sun.altitude).toBeGreaterThan((60 * Math.PI) / 180);
    expect(sun.bearingDeg).toBeGreaterThan(150);
    expect(sun.bearingDeg).toBeLessThan(230);
  });

  it('is below the horizon at midnight', () => {
    expect(sunAt(new Date('2026-10-06T21:00:00Z')).altitude).toBeLessThan(0);
  });

  it('returns a unit direction vector', () => {
    const [e, n, u] = sunAt(new Date('2026-10-06T07:00:00Z')).direction;
    expect(Math.hypot(e, n, u)).toBeCloseTo(1);
  });
});

/** Campus time (UTC+3) as hh:mm. */
const campusTime = (date: Date) =>
  new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Istanbul',
  }).format(date);

describe('nextSunEvent', () => {
  it('is the sunrise after midnight, not the evening sunset (00:59)', () => {
    // 7 October 2026, 00:59 in İstanbul: the sun rises around 07:10.
    const event = nextSunEvent(new Date('2026-10-06T21:59:00Z'));
    expect(event?.kind).toBe('sunrise');
    expect(campusTime(event!.at)).toMatch(/^07:/);
    expect(event!.at.getTime()).toBeGreaterThan(Date.UTC(2026, 9, 6, 21, 59));
  });

  it('is the sunset while the sun is up', () => {
    const event = nextSunEvent(new Date('2026-10-07T09:00:00Z')); // 12:00
    expect(event?.kind).toBe('sunset');
    expect(campusTime(event!.at)).toMatch(/^18:/);
  });

  it('is tomorrow’s sunrise after dusk', () => {
    const at = new Date('2026-10-07T18:00:00Z'); // 21:00
    const event = nextSunEvent(at);
    expect(event?.kind).toBe('sunrise');
    // Tomorrow morning, within the next 12 hours.
    expect(event!.at.getTime() - at.getTime()).toBeGreaterThan(0);
    expect(event!.at.getTime() - at.getTime()).toBeLessThan(12 * 3_600_000);
  });

  it('agrees with the sun being up or down', () => {
    for (let hour = 0; hour < 24; hour += 1) {
      const at = new Date(Date.UTC(2026, 9, 7, hour - 3, 30));
      const up = sunAt(at).altitude > 0;
      expect(nextSunEvent(at)?.kind, `${hour}:30`).toBe(
        up ? 'sunset' : 'sunrise',
      );
    }
  });
});
