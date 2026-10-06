'use client';

import { Accessibility, ArrowDownUp, Play, TriangleAlert } from 'lucide-react';
import { AnimatePresence, motion, type Transition } from 'motion/react';
import { useLocale, useTranslations } from 'next-intl';

import { compassIndex } from '@/features/campus/coords';
import {
  type Place,
  RouteError,
  type RouteResponse,
  type RouteStep,
  usePlaceDirectory,
} from '@/features/campus/queries';
import { formatDistance, formatDuration, type Locale } from '@/lib/format';

import { describePlace, PlaceGlyph, PlaceSearch } from './PlaceSearch';
import { StepIcon } from './StepIcon';
import { useRouteStore } from './store';

interface Props {
  route?: RouteResponse;
  error?: unknown;
  loading: boolean;
  now: Date;
  reducedMotion: boolean;
}

const EASE: Transition['ease'] = [0.2, 0.7, 0.2, 1];

export function DirectionsPanel({
  route,
  error,
  loading,
  now,
  reducedMotion,
}: Props) {
  const t = useTranslations('Route');
  const locale = useLocale() as Locale;
  const {
    from,
    to,
    avoidStairs,
    setFrom,
    setTo,
    swap,
    setAvoidStairs,
    setActiveStep,
  } = useRouteStore();

  const state: 'empty' | 'loading' | 'error' | 'route' =
    !from || !to
      ? 'empty'
      : loading
        ? 'loading'
        : error
          ? 'error'
          : route
            ? 'route'
            : 'loading';

  const enter = reducedMotion
    ? { initial: false as const }
    : {
        initial: { opacity: 0, y: 8 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -4 },
        transition: { duration: 0.25, ease: EASE },
      };

  return (
    <section aria-labelledby="route-heading" className="flex flex-col gap-3">
      <h2 id="route-heading" className="sr-only">
        {t('title')}
      </h2>

      <div className="grid grid-cols-[1.75rem_1fr_2.75rem] items-center rounded-2xl bg-stone-raised/75 p-1.5 shadow-[inset_0_0_0_1px_var(--hairline)]">
        <span aria-hidden className="flex justify-center">
          <span className="size-3.5 rounded-full border-[3.5px] border-route bg-stone-raised" />
        </span>
        <PlaceSearch
          label={t('fromLabel')}
          placeholder={t('from')}
          value={from}
          onChange={setFrom}
          marker="start"
        />
        <button
          type="button"
          onClick={swap}
          aria-label={t('swap')}
          disabled={!from && !to}
          className="row-span-3 mx-auto flex size-9 items-center justify-center rounded-full text-ink-muted transition-[color,background-color,transform] duration-250 ease-out-soft hover:bg-accent hover:text-ink active:rotate-180 disabled:opacity-40"
        >
          <ArrowDownUp className="size-4.5" />
        </button>
        <span
          aria-hidden
          className="flex h-3 flex-col items-center justify-between py-px"
        >
          <span className="size-0.75 rounded-full bg-ink-muted/50" />
          <span className="size-0.75 rounded-full bg-ink-muted/50" />
        </span>
        <span aria-hidden className="ml-1 h-px bg-hairline" />
        <span aria-hidden className="flex justify-center">
          <svg viewBox="0 0 16 20" className="h-4.5 w-3.5 text-brick">
            <path
              d="M8 0a8 8 0 0 0-8 8c0 5.5 8 12 8 12s8-6.5 8-12a8 8 0 0 0-8-8Z"
              fill="currentColor"
            />
            <circle cx="8" cy="8" r="3" fill="var(--stone-raised)" />
          </svg>
        </span>
        <PlaceSearch
          label={t('toLabel')}
          placeholder={t('to')}
          value={to}
          onChange={setTo}
          marker="end"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          aria-pressed={avoidStairs}
          onClick={() => setAvoidStairs(!avoidStairs)}
          className={[
            'flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-semibold transition-colors duration-150 ease-out-soft',
            avoidStairs
              ? 'bg-ink text-stone-raised'
              : 'bg-stone-raised/75 text-ink shadow-[inset_0_0_0_1px_var(--hairline)] hover:bg-stone-raised',
          ].join(' ')}
        >
          <Accessibility className="size-4" aria-hidden />
          {t('avoidStairs')}
        </button>
      </div>

      <div aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          {state === 'empty' && (
            <motion.div key="empty" {...enter}>
              <Suggestions
                exclude={[from?.id, to?.id]}
                onPick={(place, name) => {
                  const ref = { id: place.id, name };
                  if (!from) setFrom(ref);
                  else setTo(ref);
                }}
              />
            </motion.div>
          )}
          {state === 'loading' && (
            <motion.div key="loading" {...enter} aria-label={t('searching')}>
              <RouteSkeleton />
            </motion.div>
          )}
          {state === 'error' && (
            <motion.div
              key="error"
              {...enter}
              className="flex gap-3 rounded-2xl bg-brick/10 p-4 text-sm"
            >
              <TriangleAlert
                className="mt-0.5 size-4 shrink-0 text-brick"
                aria-hidden
              />
              <p>
                {error instanceof RouteError && error.kind === 'no_route'
                  ? t('noRoute')
                  : t('apiDown')}
              </p>
            </motion.div>
          )}
          {state === 'route' && route && (
            <motion.div key={`route-${route.node_ids.join()}`} {...enter}>
              <RouteSign
                route={route}
                now={now}
                locale={locale}
                onStart={() => setActiveStep(0)}
              />
              <Steps
                steps={route.steps}
                destination={to?.name ?? ''}
                reducedMotion={reducedMotion}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}

/** The route summary styled as a Turkish direction sign: white on sign blue. */
function RouteSign({
  route,
  now,
  locale,
  onStart,
}: {
  route: RouteResponse;
  now: Date;
  locale: Locale;
  onStart: () => void;
}) {
  const t = useTranslations('Route');
  const arrival = new Intl.DateTimeFormat(locale === 'tr' ? 'tr-TR' : 'en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Istanbul',
  }).format(
    // Same whole minutes as the duration shown next to it.
    new Date(
      now.getTime() + Math.max(1, Math.round(route.duration_s / 60)) * 60_000,
    ),
  );

  return (
    <div className="relative overflow-hidden rounded-2xl bg-route p-4 text-white shadow-[0_12px_32px_-12px_color-mix(in_oklch,var(--route)_70%,transparent)]">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-1 rounded-[13px] border border-white/35"
      />
      <div className="relative flex items-end justify-between gap-3">
        <p className="tabular font-display text-3xl leading-none font-bold">
          {formatDuration(route.duration_s, locale)}
        </p>
        <p className="text-right text-sm leading-tight">
          <span className="block text-xs text-white/75">{t('arrival')}</span>
          <span className="tabular font-display text-lg font-semibold">
            {arrival}
          </span>
        </p>
      </div>
      <p className="relative mt-1 text-sm text-white/85">
        {t('walkDistance', {
          distance: formatDistance(route.length_m, locale),
        })}
      </p>
      <button
        type="button"
        onClick={onStart}
        className="relative mt-4 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-white text-sm font-semibold text-route transition-transform duration-150 ease-out-soft hover:bg-white/95 active:scale-[0.98]"
      >
        <Play className="size-4 fill-current" aria-hidden />
        {t('startWalk')}
      </button>
    </div>
  );
}

function Steps({
  steps,
  destination,
  reducedMotion,
}: {
  steps: RouteStep[];
  destination: string;
  reducedMotion: boolean;
}) {
  const t = useTranslations('Route');
  const turns = useTranslations('Turns');
  const compass = useTranslations('Compass');
  const locale = useLocale() as Locale;
  const { activeStep, setActiveStep } = useRouteStore();

  return (
    <ol aria-label={t('steps')} className="relative mt-3 flex flex-col">
      {steps.map((step, index) => {
        const active = index === activeStep;
        const arrive = step.turn === 'arrive';
        const last = index === steps.length - 1;
        return (
          <motion.li
            key={`${step.node_id}-${index}`}
            className="relative"
            initial={reducedMotion ? false : { opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              delay: 0.12 + index * 0.05,
              duration: 0.25,
              ease: EASE,
            }}
          >
            {!last && (
              <span
                aria-hidden
                className="absolute top-11 bottom-[-0.25rem] left-[1.375rem] w-0.5 rounded-full bg-route/20"
              />
            )}
            <button
              type="button"
              onClick={() => setActiveStep(active ? undefined : index)}
              aria-current={active ? 'step' : undefined}
              title={t('openPano')}
              aria-label={locale === 'en' ? step.text_en : step.text_tr}
              className={[
                'grid w-full grid-cols-[2rem_1fr_auto] items-center gap-3 rounded-xl px-1.5 py-2 text-left',
                'transition-colors duration-150 ease-out-soft',
                active ? 'bg-route-soft' : 'hover:bg-accent',
              ].join(' ')}
            >
              <span
                className={[
                  'flex size-8 items-center justify-center rounded-full transition-colors duration-150',
                  arrive
                    ? 'bg-brick text-white'
                    : active
                      ? 'bg-route text-white'
                      : 'bg-route-soft text-route',
                ].join(' ')}
              >
                <StepIcon turn={step.turn} className="size-4" />
              </span>
              <span className="font-display text-md leading-tight font-semibold">
                {arrive
                  ? turns('arrive', { place: destination })
                  : step.turn === 'start'
                    ? turns('start', {
                        direction: compass(
                          String(compassIndex(step.bearing_deg)) as '0',
                        ),
                      })
                    : turns(step.turn)}
              </span>
              {step.distance_m > 0 && (
                <span className="tabular font-display text-md text-ink-muted">
                  {formatDistance(step.distance_m, locale)}
                </span>
              )}
            </button>
          </motion.li>
        );
      })}
    </ol>
  );
}

function Suggestions({
  exclude,
  onPick,
}: {
  exclude: (string | undefined)[];
  onPick: (place: Place, name: string) => void;
}) {
  const t = useTranslations('Route');
  const locale = useLocale();
  const { data: places = [], isError } = usePlaceDirectory();
  if (isError) return <p className="text-sm text-brick">{t('apiDown')}</p>;
  // Entrances first: they are what people navigate to.
  const sorted = places
    .filter((p) => !exclude.includes(p.id))
    .sort(
      (a, b) =>
        Number(b.kind === 'entrance') - Number(a.kind === 'entrance') ||
        a.name_tr.localeCompare(b.name_tr, 'tr'),
    );
  return (
    <div className="flex flex-col gap-1">
      <p className="px-1.5 pt-1 pb-1 text-xs text-ink-muted">
        {t('suggested')}
      </p>
      {sorted.map((place) => {
        const name = locale === 'en' ? place.name_en : place.name_tr;
        return (
          <button
            key={place.id}
            type="button"
            onClick={() => onPick(place, name)}
            className="flex items-center gap-3 rounded-xl px-1.5 py-1.5 text-left transition-colors duration-150 ease-out-soft hover:bg-accent"
          >
            <PlaceGlyph place={place} />
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-semibold">{name}</span>
              <span className="text-xs text-ink-muted">
                {describePlace(place, locale)}
              </span>
            </span>
          </button>
        );
      })}
      <p className="px-1.5 pt-2 text-xs leading-relaxed text-ink-muted">
        {t('coverage')}
      </p>
    </div>
  );
}

function RouteSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-hidden>
      <div className="h-36 animate-pulse rounded-2xl bg-route/15" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-3 px-1.5">
          <div className="size-8 animate-pulse rounded-full bg-accent" />
          <div className="h-4 flex-1 animate-pulse rounded bg-accent" />
        </div>
      ))}
    </div>
  );
}
