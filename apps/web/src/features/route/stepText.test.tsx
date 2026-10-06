import { render, renderHook } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import type { RouteStep } from '@/features/campus/queries';

import messages from '../../../messages/tr.json';
import { StepIcon } from './StepIcon';
import { useStepText } from './stepText';

const wrapper = ({ children }: { children: ReactNode }) => (
  <NextIntlClientProvider locale="tr" messages={messages}>
    {children}
  </NextIntlClientProvider>
);

const step = (extra: Partial<RouteStep>): RouteStep => ({
  node_id: 'n',
  turn: 'straight',
  distance_m: 12,
  bearing_deg: 0,
  text_tr: 'API metni',
  text_en: 'API text',
  indoor: false,
  floors: 0,
  ...extra,
});

describe('useStepText', () => {
  it('says a passage walks through the building', () => {
    const { result } = renderHook(() => useStepText(), { wrapper });
    expect(result.current(step({ turn: 'through', building: 'T' }), '')).toBe(
      'T Blok’un içinden geçin',
    );
    expect(
      result.current(
        step({ turn: 'exit', building: 'T', bearing_deg: 180 }),
        '',
      ),
    ).toBe('T Blok’tan çıkın, güney yönünde yürüyün');
  });

  it('falls back to the API text for a turn it does not know', () => {
    const { result } = renderHook(() => useStepText(), { wrapper });
    const newer = step({ turn: 'elevator_up' as RouteStep['turn'] });
    expect(result.current(newer, '')).toBe('API metni');
  });
});

describe('StepIcon', () => {
  it('draws an arrow for a turn it does not know', () => {
    const { container } = render(
      <StepIcon turn={'elevator_up' as RouteStep['turn']} />,
    );
    expect(container.querySelector('svg')).not.toBeNull();
  });
});
