import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import messages from '../../../messages/tr.json';

import { PanelShell } from './PanelShell';
import { type SheetSnap, snapHeights } from './sheet';

function Harness({
  sheet = true,
  initial = 'peek',
  onSnap,
}: {
  sheet?: boolean;
  initial?: SheetSnap;
  onSnap?: (snap: SheetSnap) => void;
}) {
  const [snap, setSnap] = useState<SheetSnap>(initial);
  return (
    <NextIntlClientProvider locale="tr" messages={messages}>
      <PanelShell
        sheet={sheet}
        snap={snap}
        heights={snapHeights(844)}
        onSnapChange={(next) => {
          onSnap?.(next);
          setSnap(next);
        }}
        ready
        reducedMotion
        header={<p>header</p>}
      >
        <input aria-label="Ara" />
        <input aria-label="Merdivensiz" type="checkbox" />
        <input
          aria-label="Açık liste"
          role="combobox"
          aria-controls="places"
          aria-expanded="true"
          readOnly
        />
      </PanelShell>
    </NextIntlClientProvider>
  );
}

afterEach(cleanup);

const sheetSnap = (container: HTMLElement) =>
  container.querySelector('aside')?.getAttribute('data-snap');

describe('PanelShell as a bottom sheet', () => {
  it('cycles the snaps with its handle and says what the next press does', () => {
    const { container } = render(<Harness />);
    const handle = screen.getByRole('button', { name: 'Paneli büyüt' });
    expect(handle).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(handle);
    expect(sheetSnap(container)).toBe('half');
    expect(handle).toHaveAccessibleName('Paneli tam boy aç');
    expect(handle).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(handle);
    expect(sheetSnap(container)).toBe('full');
    expect(handle).toHaveAccessibleName('Paneli küçült');

    fireEvent.click(handle);
    expect(sheetSnap(container)).toBe('peek');
  });

  it('steps with the arrow keys on the handle', () => {
    const { container } = render(<Harness />);
    const handle = screen.getByRole('button', { name: 'Paneli büyüt' });
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    expect(sheetSnap(container)).toBe('full');
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    expect(sheetSnap(container)).toBe('half');
  });

  it('lowers one snap on Escape, but lets an open place list close first', () => {
    const onSnap = vi.fn();
    const { container } = render(<Harness initial="full" onSnap={onSnap} />);
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Açık liste' }), {
      key: 'Escape',
    });
    expect(onSnap).not.toHaveBeenCalled();

    const handle = screen.getByRole('button', { name: 'Paneli küçült' });
    fireEvent.keyDown(handle, { key: 'Escape' });
    expect(sheetSnap(container)).toBe('half');
    fireEvent.keyDown(handle, { key: 'Escape' });
    fireEvent.keyDown(handle, { key: 'Escape' });
    expect(sheetSnap(container)).toBe('peek');
  });

  it('rises to full for typing, not for a switch', () => {
    const { container } = render(<Harness initial="half" />);
    fireEvent.focus(screen.getByRole('checkbox', { name: 'Merdivensiz' }));
    expect(sheetSnap(container)).toBe('half');
    fireEvent.focus(screen.getByRole('textbox', { name: 'Ara' }));
    expect(sheetSnap(container)).toBe('full');
  });
});

describe('PanelShell as the desktop card', () => {
  it('has no handle and ignores the sheet keys', () => {
    const onSnap = vi.fn();
    render(<Harness sheet={false} initial="half" onSnap={onSnap} />);
    expect(screen.queryByRole('button')).toBeNull();
    const field = screen.getByRole('textbox', { name: 'Ara' });
    fireEvent.focus(field);
    fireEvent.keyDown(field, { key: 'Escape' });
    expect(onSnap).not.toHaveBeenCalled();
  });
});
