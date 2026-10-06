import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { faceTowards, PanoThumb } from './PanoThumb';

describe('faceTowards', () => {
  it('picks the cube face closest to the walking direction', () => {
    // Front face points north (heading 0).
    expect(faceTowards(0, 0)).toBe('f');
    expect(faceTowards(80, 0)).toBe('r');
    expect(faceTowards(185, 0)).toBe('b');
    expect(faceTowards(275, 0)).toBe('l');
    expect(faceTowards(350, 0)).toBe('f');
  });

  it('accounts for the panorama heading', () => {
    // Front face points east: walking east is straight ahead.
    expect(faceTowards(90, 90)).toBe('f');
    expect(faceTowards(0, 90)).toBe('l');
  });
});

describe('PanoThumb', () => {
  it('shows the fallback until the photo loads, then hides it', () => {
    const { container, getByText, queryByText } = render(
      <PanoThumb scene="scene_1" fallback={<span>A</span>} />,
    );
    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toContain('/panos/scene_1/f_s.webp');
    expect(img?.getAttribute('loading')).toBe('lazy');
    expect(getByText('A')).toBeInTheDocument();
    fireEvent.load(img!);
    expect(queryByText('A')).toBeNull();
  });

  it('keeps the fallback and drops the image when the photo fails', () => {
    const { container, getByText } = render(
      <PanoThumb scene="scene_2" face="r" fallback={<span>B</span>} />,
    );
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(getByText('B')).toBeInTheDocument();
  });
});
