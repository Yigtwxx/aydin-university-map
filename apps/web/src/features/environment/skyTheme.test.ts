import { describe, expect, it } from 'vitest';

import type { SkyPhase } from './hooks';
import {
  precipitationIntensity,
  rainSlant,
  SKY_GRADIENTS,
  SKY_OVERLAY_PEAK,
  skyArtOf,
  type SkyKind,
  skyKindOf,
} from './skyTheme';
import type { Condition } from './weather';

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = Number.parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const channels = (hex: string) =>
  [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));

const toHex = (rgb: number[]) =>
  `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`;

/** Contrast of `alpha` white text (the sheet's secondary text) on `hex`. */
function textContrast(hex: string, alpha: number): number {
  const text = toHex(channels(hex).map((c) => alpha * 255 + (1 - alpha) * c));
  return (luminance(text) + 0.05) / (luminance(hex) + 0.05);
}

/** `hex` with white laid over it at `alpha`, as the cloud and fog layers do. */
const veiled = (hex: string, alpha: number) =>
  toHex(channels(hex).map((c) => alpha * 255 + (1 - alpha) * c));

/** A colour halfway between two, in sRGB like the gradient. */
function mix(a: string, b: string): string {
  const [ca, cb] = [channels(a), channels(b)];
  return toHex(ca.map((c, i) => (c + cb[i]!) / 2));
}

describe('SKY_GRADIENTS', () => {
  const stops = Object.entries(SKY_GRADIENTS).flatMap(([kind, phases]) =>
    Object.entries(phases).flatMap(([phase, [top, bottom]]) =>
      [top, mix(top, bottom), bottom].map((color) => ({
        kind: kind as SkyKind,
        sky: `${kind}/${phase}`,
        color,
      })),
    ),
  );

  it.each(stops)(
    'keeps secondary text legible on $sky ($color)',
    ({ color }) => {
      expect(textContrast(color, 0.9)).toBeGreaterThanOrEqual(4.5);
    },
  );

  // Under the thickest cloud or fog, the main text still reads.
  it.each(stops)(
    'keeps white text legible under cloud on $sky ($color)',
    ({ kind, color }) => {
      expect(
        textContrast(veiled(color, SKY_OVERLAY_PEAK[kind]), 1),
      ).toBeGreaterThanOrEqual(4.5);
    },
  );
});

describe('skyKindOf', () => {
  it.each<[Condition | undefined, string]>([
    [undefined, 'clear'],
    ['mainlyClear', 'clear'],
    ['partlyCloudy', 'partly'],
    ['drizzle', 'rain'],
    ['showers', 'rain'],
    ['storm', 'storm'],
    ['snow', 'snow'],
  ])('puts %s under the %s sky', (condition, kind) => {
    expect(skyKindOf(condition)).toBe(kind);
  });
});

describe('skyArtOf', () => {
  it.each<[SkyPhase, string]>([
    ['day', 'sun'],
    ['golden', 'sunset'],
    ['twilight', 'moon'],
    ['night', 'moon'],
  ])('lights an open sky at %s with the %s', (phase, glow) => {
    expect(skyArtOf('clear', phase).glow).toBe(glow);
  });

  it('shows stars only on an open night sky', () => {
    expect(skyArtOf('clear', 'night').stars).toBe(true);
    expect(skyArtOf('clear', 'day').stars).toBe(false);
    expect(skyArtOf('overcast', 'night').stars).toBe(false);
  });

  it('draws puffs on a partly cloudy sky and a deck when overcast', () => {
    expect(skyArtOf('partly', 'day').clouds).toBe('cumulus');
    expect(skyArtOf('overcast', 'day').clouds).toBe('stratus');
    expect(skyArtOf('clear', 'day').clouds).toBeUndefined();
  });

  it('rains in a storm, snows in snow, and hides the sun behind cloud', () => {
    expect(skyArtOf('storm', 'day').precipitation).toBe('rain');
    expect(skyArtOf('snow', 'day').precipitation).toBe('snow');
    expect(skyArtOf('overcast', 'day').glow).toBeUndefined();
  });
});

describe('precipitationIntensity', () => {
  it('rains harder in showers than in drizzle', () => {
    expect(precipitationIntensity('showers')).toBeGreaterThan(
      precipitationIntensity('drizzle'),
    );
  });
});

describe('rainSlant', () => {
  it('drifts with the wind: right in a westerly, left in an easterly', () => {
    expect(rainSlant({ speedKmh: 30, fromDeg: 270 })).toBeGreaterThan(0);
    expect(rainSlant({ speedKmh: 30, fromDeg: 90 })).toBeLessThan(0);
  });

  it('slants more in a stronger wind', () => {
    expect(rainSlant({ speedKmh: 40, fromDeg: 270 })).toBeGreaterThan(
      rainSlant({ speedKmh: 10, fromDeg: 270 }),
    );
  });

  it('falls straight in a wind along the screen', () => {
    expect(Math.abs(rainSlant({ speedKmh: 30, fromDeg: 0 }))).toBeLessThan(
      1e-9,
    );
  });
});
