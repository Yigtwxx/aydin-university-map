import { describe, expect, it } from 'vitest';

import { conditionOf, precipitationOf, windFromIndex } from './weather';

describe('conditionOf', () => {
  it.each([
    [0, 'clear'],
    [1, 'mainlyClear'],
    [2, 'partlyCloudy'],
    [3, 'overcast'],
    [45, 'fog'],
    [53, 'drizzle'],
    [63, 'rain'],
    [81, 'showers'],
    [73, 'snow'],
    [86, 'snow'],
    [95, 'storm'],
  ] as const)('maps WMO code %i to %s', (code, condition) => {
    expect(conditionOf(code)).toBe(condition);
  });
});

describe('precipitationOf', () => {
  it('renders rain for showers and storms, snow for snow, nothing when dry', () => {
    expect(precipitationOf('showers')).toBe('rain');
    expect(precipitationOf('storm')).toBe('rain');
    expect(precipitationOf('snow')).toBe('snow');
    expect(precipitationOf('overcast')).toBeUndefined();
  });
});

describe('windFromIndex', () => {
  it('rounds to the nearest of eight compass points and wraps north', () => {
    expect(windFromIndex(0)).toBe(0);
    expect(windFromIndex(44)).toBe(1);
    expect(windFromIndex(350)).toBe(0);
    expect(windFromIndex(-90)).toBe(6);
  });
});
