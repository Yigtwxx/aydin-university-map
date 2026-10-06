// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';

import { terrarium } from './earth';
import { toCredits } from './GoogleTiles';

describe('terrarium', () => {
  it('decodes sea level and heights', () => {
    expect(terrarium(128, 0, 0)).toBe(0);
    expect(terrarium(128, 35, 128)).toBeCloseTo(35.5, 5);
    expect(terrarium(127, 255, 0)).toBe(-1);
  });
});

describe('toCredits', () => {
  it('keeps text and https logos, never markup', () => {
    const credits = toCredits([
      { type: 'string', value: 'Google' },
      { type: 'string', value: 'Google' },
      {
        type: 'html',
        value:
          '<a href="https://x.test"><img src="https://x.test/logo.png"></a><script>alert(1)</script>Data SIO',
      },
      { type: 'image', value: 'http://insecure.test/logo.png' },
    ]);
    expect(credits).toEqual([
      { text: 'Google' },
      { image: 'https://x.test/logo.png' },
      { text: 'alert(1)Data SIO' },
    ]);
  });
});
