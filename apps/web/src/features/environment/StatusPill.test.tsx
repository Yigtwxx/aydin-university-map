import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from 'vitest';

import messages from '../../../messages/tr.json';

import { type Sky, phaseOf } from './hooks';
import { StatusPill } from './StatusPill';
import { useEnvironmentStore } from './store';
import { sunAt } from './sun';
import { type Condition, conditionOf, type Weather } from './weather';

const weather: Weather = {
  temperature_c: 15,
  weather_code: 1,
  is_day: false,
  wind_speed_kmh: 5,
  wind_direction_deg: 45,
  visibility_m: 25_000,
  cloud_cover_pct: 46,
  stale: false,
} as Weather;

function renderPill(
  live: Date,
  condition: Condition = conditionOf(weather.weather_code),
) {
  const sun = sunAt(live);
  const sky: Sky = { sun, phase: phaseOf(sun.altitude) };
  return render(
    <NextIntlClientProvider
      locale="tr"
      messages={messages}
      timeZone="Europe/Istanbul"
    >
      <StatusPill
        now={live}
        live={live}
        sky={sky}
        weather={weather}
        condition={condition}
        weatherError={false}
      />
    </NextIntlClientProvider>,
  );
}

const open = () =>
  fireEvent.click(
    screen.getByRole('button', { name: /Saat ve hava durumu ayrıntıları/ }),
  );

// The glass surface measures itself; jsdom has no ResizeObserver.
beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterAll(() => vi.unstubAllGlobals());

afterEach(() => {
  cleanup();
  act(() => useEnvironmentStore.getState().backToLive());
});

describe('StatusPill', () => {
  it('keeps the weather in words for the sheet and screen readers', () => {
    renderPill(new Date('2026-10-07T09:00:00Z'));
    const words = screen.getByText('Az bulutlu');
    expect(words).toHaveClass('sr-only');
    expect(
      screen.getByRole('button', { name: /Az bulutlu/ }),
    ).toBeInTheDocument();
  });
});

describe('StatusPill details', () => {
  it('shows the coming sunrise at 00:59, not the evening sunset', async () => {
    renderPill(new Date('2026-10-06T21:59:00Z')); // 00:59 campus time
    open();
    expect(await screen.findByText('Gün doğumu')).toBeInTheDocument();
    expect(screen.queryByText('Gün batımı')).toBeNull();
  });

  it('shows the sunset while the sun is up', async () => {
    renderPill(new Date('2026-10-07T09:00:00Z')); // 12:00
    open();
    expect(await screen.findByText('Gün batımı')).toBeInTheDocument();
  });

  it('does not call a previewed hour "now"', async () => {
    renderPill(new Date('2026-10-07T09:00:00Z'));
    open();
    expect(await screen.findByText('Florya, şu an')).toBeInTheDocument();
    act(() => useEnvironmentStore.getState().setHour(21));
    expect(screen.queryByText('Florya, şu an')).toBeNull();
    expect(screen.getByText('Florya, canlı hava durumu')).toBeInTheDocument();
  });

  it('does not call a previewed weather "now" either', async () => {
    renderPill(new Date('2026-10-07T09:00:00Z'));
    open();
    expect(await screen.findByText('Florya, şu an')).toBeInTheDocument();
    act(() => useEnvironmentStore.getState().setCondition('snow'));
    expect(screen.queryByText('Florya, şu an')).toBeNull();
  });
});
