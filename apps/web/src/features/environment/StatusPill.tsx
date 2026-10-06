'use client';

import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudMoon,
  CloudRain,
  CloudSnow,
  CloudSun,
  Eye,
  type LucideIcon,
  Moon,
  Sun,
  Sunrise,
  Sunset,
  Wind,
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { createElement } from 'react';

import { Glass } from '@/components/glass/Glass';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

import { Slider } from '@/components/ui/slider';

import type { Sky } from './hooks';
import { campusHour, useEnvironmentStore } from './store';
import {
  type Condition,
  conditionOf,
  type Weather,
  windFromIndex,
} from './weather';

const CAMPUS_TZ = 'Europe/Istanbul';

const DAY_ICONS: Record<Condition, LucideIcon> = {
  clear: Sun,
  mainlyClear: CloudSun,
  partlyCloudy: CloudSun,
  overcast: Cloud,
  fog: CloudFog,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  showers: CloudRain,
  snow: CloudSnow,
  storm: CloudLightning,
};

function iconFor(condition: Condition | undefined, isDay: boolean): LucideIcon {
  if (!condition) return isDay ? Sun : Moon;
  if (isDay) return DAY_ICONS[condition];
  if (condition === 'clear') return Moon;
  if (condition === 'mainlyClear' || condition === 'partlyCloudy')
    return CloudMoon;
  return DAY_ICONS[condition];
}

const SUNNY = new Set<Condition | undefined>([
  undefined,
  'clear',
  'mainlyClear',
  'partlyCloudy',
]);

/** Sun in ochre, moon in Marmara blue, clouds and rain in muted ink. */
function iconTint(condition: Condition | undefined, isDay: boolean): string {
  if (!SUNNY.has(condition)) return 'text-ink-muted';
  return isDay ? 'text-ochre' : 'text-marmara';
}

function WeatherIcon({
  condition,
  isDay,
  className,
  strokeWidth,
}: {
  condition?: Condition;
  isDay: boolean;
  className: string;
  strokeWidth: number;
}) {
  return createElement(iconFor(condition, isDay), {
    className,
    strokeWidth,
    'aria-hidden': true,
  });
}

interface Props {
  /** The time the scene shows (live, or a previewed hour). */
  now: Date;
  /** The real current time. */
  live: Date;
  sky: Sky;
  weather?: Weather;
  /** The sky the scene shows (live, or a previewed weather). */
  condition?: Condition;
  weatherError: boolean;
}

const PREVIEW_CONDITIONS: Condition[] = [
  'clear',
  'partlyCloudy',
  'overcast',
  'rain',
  'snow',
  'fog',
];

/** Campus clock and live weather; opens a sheet with details and previews. */
export function StatusPill({
  now,
  live,
  sky,
  weather,
  condition,
  weatherError,
}: Props) {
  const {
    hour,
    condition: previewCondition,
    setHour,
    setCondition,
    backToLive,
  } = useEnvironmentStore();
  const previewing = hour !== undefined || previewCondition !== undefined;
  const t = useTranslations('Environment');
  const compass = useTranslations('Compass');
  const locale = useLocale();
  const intl = locale === 'tr' ? 'tr-TR' : 'en-GB';
  const time = (date: Date) =>
    new Intl.DateTimeFormat(intl, {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: CAMPUS_TZ,
    }).format(date);
  const day = new Intl.DateTimeFormat(intl, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: CAMPUS_TZ,
  }).format(now);
  const number = new Intl.NumberFormat(intl, { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat(intl, { style: 'percent' });

  const isDay = sky.phase === 'day' || sky.phase === 'golden';
  const liveCondition = weather ? conditionOf(weather.weather_code) : undefined;
  // Show the next sun event: sunset during the day, sunrise at night.
  const nextIsSunset = sky.sunset !== undefined && now < sky.sunset;
  const sunEvent = nextIsSunset ? sky.sunset : sky.sunrise;

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Glass
            as="button"
            type="button"
            radius={999}
            className={[
              'flex h-11 items-center gap-3 pr-4 pl-3 text-sm transition-transform duration-150 ease-out-soft active:scale-[0.98]',
              previewing ? 'ring-2 ring-route/60' : '',
            ].join(' ')}
            aria-label={t('details')}
          />
        }
      >
        <span className="flex items-center gap-2">
          <WeatherIcon
            condition={condition}
            isDay={isDay}
            className={`size-5 ${iconTint(condition, isDay)}`}
            strokeWidth={2}
          />
          {weather ? (
            <>
              <span className="tabular font-display text-md leading-none font-semibold">
                {number.format(weather.temperature_c)}°
              </span>
              <span className="hidden text-ink-muted lg:inline">
                {condition && t(`condition.${condition}`)}
              </span>
            </>
          ) : (
            <span className="text-ink-muted">
              {weatherError ? t('unavailableShort') : '…'}
            </span>
          )}
        </span>
        <span aria-hidden className="h-5 w-px bg-hairline" />
        <span className="flex items-baseline gap-2">
          <time
            dateTime={now.toISOString()}
            suppressHydrationWarning
            className="tabular font-display text-md leading-none font-semibold"
          >
            {time(now)}
          </time>
          {previewing ? (
            <span className="rounded-full bg-route px-2 py-0.5 text-xs font-semibold text-white">
              {t('previewBadge')}
            </span>
          ) : (
            <span className="hidden text-ink-muted capitalize xl:inline">
              {day}
            </span>
          )}
        </span>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={10}
        className="glass glass-thick w-[22rem] gap-4 rounded-[22px] bg-transparent p-5 ring-0"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs text-ink-muted">{t('now')}</p>
            <p className="tabular mt-1 font-display text-3xl leading-none font-semibold">
              {weather ? `${number.format(weather.temperature_c)}°` : '—'}
            </p>
            <p className="mt-1 text-sm">
              {liveCondition
                ? t(`condition.${liveCondition}`)
                : t('unavailable')}
            </p>
          </div>
          <WeatherIcon
            condition={liveCondition}
            isDay={weather?.is_day ?? isDay}
            className={`size-12 ${iconTint(liveCondition, weather?.is_day ?? isDay)}`}
            strokeWidth={1.5}
          />
        </div>
        {weather && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Detail icon={Wind} label={t('wind')}>
              {t('windValue', {
                direction: compass(
                  String(windFromIndex(weather.wind_direction_deg)) as '0',
                ),
                speed: number.format(weather.wind_speed_kmh),
              })}
            </Detail>
            <Detail icon={Eye} label={t('visibility')}>
              {weather.visibility_m >= 1000
                ? `${number.format(weather.visibility_m / 1000)} km`
                : `${number.format(weather.visibility_m)} m`}
            </Detail>
            <Detail icon={Cloud} label={t('clouds')}>
              {percent.format(weather.cloud_cover_pct / 100)}
            </Detail>
            {sunEvent && (
              <Detail
                icon={nextIsSunset ? Sunset : Sunrise}
                label={nextIsSunset ? t('sunset') : t('sunrise')}
              >
                {time(sunEvent)}
              </Detail>
            )}
          </dl>
        )}
        <section
          aria-labelledby="preview-heading"
          className="flex flex-col gap-3 border-t border-hairline pt-4"
        >
          <div className="flex items-center justify-between">
            <h3 id="preview-heading" className="text-sm font-semibold">
              {t('preview')}
            </h3>
            {previewing && (
              <button
                type="button"
                onClick={backToLive}
                className="rounded-full px-2 py-1 text-xs font-semibold text-route hover:bg-route-soft"
              >
                {t('backToLive')}
              </button>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between text-xs text-ink-muted">
              <span id="preview-time">{t('time')}</span>
              <span className="tabular font-display text-md font-semibold text-ink">
                {time(now)}
              </span>
            </div>
            <Slider
              aria-labelledby="preview-time"
              min={0}
              max={23.75}
              step={0.25}
              value={[hour ?? campusHour(live)]}
              onValueChange={(value) =>
                setHour(Array.isArray(value) ? value[0] : value)
              }
            />
            <div className="tabular flex justify-between text-[11px] text-ink-muted">
              <span>00</span>
              <span>06</span>
              <span>12</span>
              <span>18</span>
              <span>24</span>
            </div>
          </div>
          <div
            role="group"
            aria-label={t('weather')}
            className="flex flex-wrap gap-1.5"
          >
            <PreviewChip
              pressed={previewCondition === undefined}
              onClick={() => setCondition(undefined)}
            >
              {t('live')}
            </PreviewChip>
            {PREVIEW_CONDITIONS.map((c) => (
              <PreviewChip
                key={c}
                pressed={previewCondition === c}
                onClick={() => setCondition(c)}
              >
                <WeatherIcon
                  condition={c}
                  isDay
                  className="size-3.5"
                  strokeWidth={2}
                />
                {t(`condition.${c}`)}
              </PreviewChip>
            ))}
          </div>
        </section>
        <p className="border-t border-hairline pt-3 text-xs text-ink-muted">
          {weather?.stale ? `${t('stale')} ` : ''}
          {t('source')}
        </p>
      </PopoverContent>
    </Popover>
  );
}

function PreviewChip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={[
        'flex h-7 items-center gap-1 rounded-full px-2.5 text-xs font-semibold transition-colors duration-150 ease-out-soft',
        pressed
          ? 'bg-ink text-stone-raised'
          : 'bg-accent text-ink hover:bg-stone-deep/60',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

function Detail({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 size-4 text-ink-muted" aria-hidden />
      <div>
        <dt className="text-xs text-ink-muted">{label}</dt>
        <dd className="tabular font-semibold">{children}</dd>
      </div>
    </div>
  );
}
