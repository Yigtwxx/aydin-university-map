import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { anchors } from '@/features/campus/anchors';
import type { Place } from '@/features/campus/queries';

import messages from '../../../messages/tr.json';
import type { ZoomTier } from './cameraStore';
import { PoiLayer } from './PoiLayer';

const place = (
  id: string,
  name: string,
  extra: Partial<Place> = {},
): Place => ({
  id,
  name_tr: name,
  name_en: name,
  kind: 'indoor',
  building: null,
  node_ids: [id],
  area_tr: '',
  area_en: '',
  ...extra,
});

const places: Place[] = [
  place('bk', 'Burger King', {
    category: 'food',
    pin_enu: [14.4, 34.8],
    pin_source: 'entrance',
    building: 'C',
  }),
  place('sb', 'Starbucks', {
    category: 'cafe',
    pin_enu: [16.3, 7.5],
    pin_source: 'storefront',
  }),
  // Two businesses behind one door: one marker.
  place('fit', 'Fitness Salonu', { category: 'sports', pin_enu: [-4.2, 34.2] }),
  place('gym', 'Spor Salonu', { category: 'sports', pin_enu: [-4.2, 34.2] }),
  // Not measured yet: no pin.
  place('later', 'Kırtasiye', { category: 'shop', pin_enu: null }),
  // Not a business.
  place('a', 'A Blok Girişi', { kind: 'entrance', building: 'A' }),
];

function renderLayer({
  tier = 'near',
  quiet = false,
  hiddenId,
  onPick = vi.fn(),
}: {
  tier?: ZoomTier;
  quiet?: boolean;
  hiddenId?: string;
  onPick?: (place: Place) => void;
} = {}) {
  return render(
    <NextIntlClientProvider locale="tr" messages={messages}>
      <PoiLayer
        places={places}
        tier={tier}
        quiet={quiet}
        hiddenId={hiddenId}
        onPick={onPick}
      />
    </NextIntlClientProvider>,
  );
}

afterEach(cleanup);

describe('PoiLayer', () => {
  it('pins every business with a pin, and nothing else', () => {
    renderLayer();
    const names = screen
      .getAllByRole('button')
      .map((b) => b.getAttribute('aria-label'));
    expect(names).toEqual([
      'Burger King, Restoran, C Blok girişi. Yol tarifi al',
      'Starbucks, Kafe. Yol tarifi al',
      'Fitness Salonu, Spor. Yol tarifi al',
      'Spor Salonu, Spor. Yol tarifi al',
    ]);
  });

  it('gives the businesses behind one door one marker on the pin', () => {
    renderLayer();
    expect(
      [...anchors.keys()].filter((id) => id.startsWith('pin-poi-')),
    ).toEqual(['pin-poi-bk', 'pin-poi-sb', 'pin-poi-fit']);
    // Map world: x east, y up, z south.
    expect(anchors.get('pin-poi-bk')?.position.toArray()).toEqual([
      14.4, 0.6, -34.8,
    ]);
    expect(screen.getByText('Fitness Salonu ve Spor Salonu')).toBeVisible();
  });

  it('names businesses only up close, and not around a route', () => {
    renderLayer({ tier: 'mid' });
    expect(screen.getAllByRole('button')).toHaveLength(4);
    expect(screen.queryByText('Starbucks')).toBeNull();
    cleanup();
    renderLayer({ quiet: true });
    expect(screen.queryByText('Starbucks')).toBeNull();
    cleanup();
    renderLayer();
    expect(screen.getByText('Starbucks')).toBeVisible();
  });

  it('shows no pins on the campus overview', () => {
    renderLayer({ tier: 'far' });
    expect(screen.queryAllByRole('button')).toEqual([]);
    expect([...anchors.keys()].some((id) => id.startsWith('pin-poi-'))).toBe(
      false,
    );
  });

  it('makes a business the destination when picked', () => {
    const onPick = vi.fn();
    renderLayer({ onPick });
    fireEvent.click(screen.getByRole('button', { name: /^Starbucks, Kafe/ }));
    expect(onPick).toHaveBeenCalledWith(places[1]);
  });

  it('steps aside for the destination pin, with its spot', () => {
    renderLayer({ hiddenId: 'gym' });
    expect(
      screen
        .getAllByRole('button')
        .map((b) => b.getAttribute('aria-label')?.split(',')[0]),
    ).toEqual(['Burger King', 'Starbucks']);
  });
});
