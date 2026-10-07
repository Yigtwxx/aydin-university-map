import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { anchors } from '@/features/campus/anchors';
import type { GraphNode } from '@/features/campus/types';

import messages from '../../../messages/tr.json';
import { MapOverlays } from './MapOverlays';

const node = (id: string, east: number, north: number): GraphNode => ({
  id,
  kind: 'entrance',
  lat: 0,
  lng: 0,
  alt_m: 0,
  enu: [east, north, 0],
  heading_deg: 0,
  label: { tr: id, en: id },
  area: { tr: '', en: '' },
  building: null,
});

const door = node('door', 10, 20);
const gate = node('gate', -40, 5);

function renderOverlays(props: Partial<ComponentProps<typeof MapOverlays>>) {
  render(
    <NextIntlClientProvider locale="tr" messages={messages}>
      <MapOverlays
        nodes={[door, gate]}
        buildings={[]}
        route={[]}
        labelOf={(n) => n.label.tr}
        onOpenPano={vi.fn()}
        onPickPlace={vi.fn()}
        {...props}
      />
    </NextIntlClientProvider>,
  );
}

const positionOf = (id: string) => anchors.get(id)?.position.toArray();

afterEach(cleanup);

describe('MapOverlays destination', () => {
  it('pins a destination on its node', () => {
    renderOverlays({ destinationNodeId: 'door', destinationLabel: 'Kapı' });
    expect(positionOf('pin-end')).toEqual([10, 0.6, -20]);
  });

  it('pins a business at its pin, not its panorama’s borrowed spot', () => {
    renderOverlays({
      destinationNodeId: 'door',
      destinationEnu: [14, 25],
      destinationLabel: 'Burger King',
    });
    expect(positionOf('pin-end')).toEqual([14, 0.6, -25]);
  });

  it('pins a business of its own (no node of that id) at its pin', () => {
    renderOverlays({
      destinationNodeId: 'poi:atm',
      destinationEnu: [12, 6],
      destinationLabel: 'ATM',
    });
    expect(positionOf('pin-end')).toEqual([12, 0.6, -6]);
  });

  it('keeps the pin there once the route ends at the door', () => {
    renderOverlays({
      route: [gate, door],
      destinationNodeId: 'door',
      destinationEnu: [14, 25],
      destinationLabel: 'Burger King',
    });
    expect(positionOf('pin-start')).toEqual([-40, 0.6, -5]);
    expect(positionOf('pin-end')).toEqual([14, 0.6, -25]);
  });

  it('shows a business’s own 360° spot at its pin', () => {
    renderOverlays({ focusNodeId: 'door', focusEnu: [14, 25] });
    expect(positionOf('pin-focus')).toEqual([14, 0.6, -25]);
  });
});
