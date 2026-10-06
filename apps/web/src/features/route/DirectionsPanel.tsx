'use client';

import { cn } from 'cn';
import {
  Accessibility,
  ArrowDownUp,
  Check,
  Play,
  TriangleAlert,
} from 'lucide-react';
import { AnimatePresence, motion, type Transition } from 'motion/react';
import { useLocale, useTranslations } from 'next-intl';
import { type RefObject, useEffect, useMemo, useRef } from 'react';

import { Switch } from '@/components/ui/switch';
import { bearingDeg, compassIndex } from '@/features/campus/coords';
import {
  type Place,
  RouteError,
  type RouteResponse,
  type RouteStep,
  useCampusGraph,
} from '@/features/campus/queries';
import { formatDistance, formatDuration, type Locale } from '@/lib/format';

import { CopyLinkButton, useCopyLink } from './CopyLinkButton';
import { type CubeFace, faceTowards, PanoThumb } from './PanoThumb';
import { PlaceBrowser } from './PlaceBrowser';
import { PlaceSearch } from './PlaceSearch';
import { StepIcon } from './StepIcon';
import { useRouteStore } from './store';

interface Props {
  route?: RouteResponse;
  error?: unknown;
  loading: boolean;
  now: Date;
  reducedMotion: boolean;
  /**
   * `panel`: the desktop card. `sheet`: the mobile bottom sheet, where the
   * route summary leads so the peek height shows it above the fields.
   */
  layout?: 'panel' | 'sheet';
}

const EASE: Transition['ease'] = [0.2, 0.7, 0.2, 1];
const NONE: string[] = [];

export function DirectionsPanel({
  route,
  error,
  loading,
  now,
  reducedMotion,
  layout = 'panel',
}: Props) {
  const t = useTranslations('Route');
  const locale = useLocale() as Locale;
  const {
    from,
    to,
    avoidStairs,
    setFrom,
    setTo,
    setAvoidStairs,
    setActiveStep,
  } = useRouteStore();
  const fromInput = useRef<HTMLInputElement>(null);
  const focusStart = useRef(false);

  // Search first: one "Where to?" field until a place is chosen, then the
  // full from/to card.
  const planning = Boolean(from || to);
  const state: 'browse' | 'pickStart' | 'loading' | 'error' | 'route' =
    !from && !to
      ? 'browse'
      : !from || !to
        ? 'pickStart'
        : loading
          ? 'loading'
          : error
            ? 'error'
            : route
              ? 'route'
              : 'loading';

  // Typing a destination continues straight into the start field. Only for
  // keyboard and mouse: on touch screens it would pop the keyboard up.
  useEffect(() => {
    if (!focusStart.current || !planning || from) return;
    focusStart.current = false;
    fromInput.current?.focus();
  }, [planning, from]);

  const enter = reducedMotion
    ? { initial: false as const }
    : {
        initial: { opacity: 0, y: 6 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -4 },
        transition: { duration: 0.2, ease: EASE },
      };

  const pick = (place: Place, name: string) => {
    const ref = { id: place.id, name };
    if (!to) setTo(ref);
    else setFrom(ref);
  };

  const sheet = layout === 'sheet';
  const summary = route && (
    <RouteSummary
      route={route}
      now={now}
      locale={locale}
      stepFree={avoidStairs}
      compact={sheet}
      onStart={() => setActiveStep(0)}
    />
  );

  return (
    <section aria-labelledby="route-heading" className="flex flex-col gap-3">
      <h2 id="route-heading" className="sr-only">
        {t('title')}
      </h2>

      {/* The steps below are the live region that announces a new route. */}
      <AnimatePresence initial={false}>
        {sheet && state === 'route' && route && (
          <motion.div key={`summary-${route.node_ids.join()}`} {...enter}>
            {summary}
          </motion.div>
        )}
      </AnimatePresence>

      {planning ? (
        <RouteFields fromInput={fromInput} />
      ) : (
        <PlaceSearch
          variant="hero"
          label={t('searchLabel')}
          placeholder={t('search')}
          value={to}
          onChange={(place) => {
            focusStart.current = window.matchMedia('(pointer: fine)').matches;
            setTo(place);
          }}
        />
      )}

      {planning && (
        <label className="flex h-9 cursor-pointer items-center gap-2.5 rounded-control px-2 text-sm transition-colors duration-150 ease-out-soft hover:bg-fill">
          <Accessibility className="size-4 text-ink-muted" aria-hidden />
          <span className="flex-1">{t('avoidStairs')}</span>
          <Switch
            checked={avoidStairs}
            onCheckedChange={(checked) => setAvoidStairs(checked)}
            className="data-unchecked:bg-fill-strong data-unchecked:shadow-[inset_0_0_0_1px_var(--hairline)] dark:data-unchecked:bg-fill-strong"
          />
        </label>
      )}

      <div aria-live="polite" className="flex flex-col">
        <AnimatePresence mode="wait" initial={false}>
          {state === 'browse' && (
            <motion.div key="browse" {...enter} className="pt-1">
              <PlaceBrowser exclude={NONE} onPick={pick} />
            </motion.div>
          )}
          {state === 'pickStart' && (
            <motion.div key="pickStart" {...enter} className="pt-1">
              <p className="px-0.5 text-md font-medium tracking-heading">
                {t('pickStart')}
              </p>
              <p className="mb-3 px-0.5 text-xs text-ink-muted">
                {t('pickStartHint')}
              </p>
              <PlaceBrowser exclude={[from?.id, to?.id]} onPick={pick} />
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
              className="flex gap-3 rounded-card bg-brick/10 p-3.5 text-sm leading-relaxed"
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
            <motion.div
              key={`route-${route.node_ids.join()}`}
              {...enter}
              className="flex flex-col"
            >
              {!sheet && summary}
              <Steps
                route={route}
                origin={from?.name ?? ''}
                destination={to?.name ?? ''}
                reducedMotion={reducedMotion}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {(state === 'browse' || state === 'pickStart') && (
        <p className="px-0.5 text-xs leading-relaxed text-ink-muted">
          {t('coverage')}
        </p>
      )}
    </section>
  );
}

/** Start and destination as one card, joined by the route's dotted spine. */
function RouteFields({
  fromInput,
}: {
  fromInput: RefObject<HTMLInputElement | null>;
}) {
  const t = useTranslations('Route');
  const { from, to, setFrom, setTo, swap } = useRouteStore();
  return (
    <div className="grid grid-cols-[2rem_1fr_2.5rem] items-center rounded-card bg-fill py-1 pl-1">
      <span aria-hidden className="flex justify-center">
        <span className="size-3 rounded-full border-[3px] border-route bg-stone-raised" />
      </span>
      <PlaceSearch
        variant="row"
        label={t('fromLabel')}
        placeholder={t('from')}
        value={from}
        onChange={setFrom}
        inputRef={fromInput}
      />
      <button
        type="button"
        onClick={swap}
        aria-label={t('swap')}
        title={t('swap')}
        disabled={!from || !to}
        className="row-span-3 mx-auto flex size-8 items-center justify-center rounded-full text-ink-muted transition-[color,background-color,transform] duration-250 ease-out-soft hover:bg-fill-strong hover:text-ink active:rotate-180 disabled:opacity-35 disabled:hover:bg-transparent"
      >
        <ArrowDownUp className="size-4" />
      </button>
      <span
        aria-hidden
        className="flex h-2 flex-col items-center justify-between"
      >
        <span className="size-0.5 rounded-full bg-ink-faint" />
        <span className="size-0.5 rounded-full bg-ink-faint" />
      </span>
      <span aria-hidden className="h-px bg-hairline" />
      <span aria-hidden className="flex justify-center">
        <svg viewBox="0 0 16 20" className="h-4 w-3.5 text-brick">
          <path
            d="M8 0a8 8 0 0 0-8 8c0 5.5 8 12 8 12s8-6.5 8-12a8 8 0 0 0-8-8Z"
            fill="currentColor"
          />
          <circle cx="8" cy="8" r="3" fill="#fff" />
        </svg>
      </span>
      <PlaceSearch
        variant="row"
        label={t('toLabel')}
        placeholder={t('to')}
        value={to}
        onChange={setTo}
      />
    </div>
  );
}

function RouteSummary({
  route,
  now,
  locale,
  stepFree,
  compact,
  onStart,
}: {
  route: RouteResponse;
  now: Date;
  locale: Locale;
  stepFree: boolean;
  /** One row (duration, copy link, start) for the bottom sheet's peek. */
  compact: boolean;
  onStart: () => void;
}) {
  const t = useTranslations('Route');
  const link = useCopyLink();
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

  if (compact)
    return (
      <div className="flex items-center gap-2 pb-0.5">
        <div className="min-w-0 flex-1 px-0.5">
          <p className="tabular text-2xl leading-none font-semibold tracking-display">
            {formatDuration(route.duration_s, locale)}
          </p>
          {/* The copy confirmation briefly takes the meta line's place. */}
          {link.state === 'idle' ? (
            <p className="tabular mt-1.5 truncate text-xs text-ink-muted">
              {t('walkDistance', {
                distance: formatDistance(route.length_m, locale),
              })}
              {' · '}
              {t('arrivalAt', { time: arrival })}
              {stepFree && (
                <span className="ml-1.5 inline-flex items-center gap-0.5 align-bottom text-ink">
                  <Accessibility className="size-3.5" aria-hidden />
                  {t('stepFree')}
                </span>
              )}
            </p>
          ) : (
            <p
              aria-hidden
              className={cn(
                'mt-1.5 flex items-center gap-1 truncate text-xs font-medium',
                link.state === 'copied' ? 'text-route' : 'text-brick',
              )}
            >
              {link.state === 'copied' ? (
                <Check className="size-3.5 shrink-0" aria-hidden />
              ) : (
                <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
              )}
              {link.state === 'copied' ? t('linkCopiedShort') : t('copyFailed')}
            </p>
          )}
        </div>
        <CopyLinkButton link={link} expand={false} />
        <button
          type="button"
          onClick={onStart}
          aria-label={t('startWalk')}
          className="flex h-10 shrink-0 items-center gap-1.5 rounded-full bg-route pr-4 pl-3.5 text-md font-medium text-on-route shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_6px_16px_-8px_var(--route)] transition-[filter,transform] duration-150 ease-out-soft hover:brightness-110 active:scale-[0.97]"
        >
          <Play className="size-3.5 fill-current" aria-hidden />
          {t('startShort')}
        </button>
      </div>
    );

  return (
    <div className="flex flex-col gap-3.5 pt-1 pb-3">
      <div className="flex items-end justify-between gap-3 px-0.5">
        <div className="min-w-0">
          <p className="tabular text-3xl leading-none font-semibold tracking-display">
            {formatDuration(route.duration_s, locale)}
          </p>
          <p className="mt-2 text-sm text-ink-muted">
            {t('walkDistance', {
              distance: formatDistance(route.length_m, locale),
            })}
            {stepFree && (
              <span className="ml-2 inline-flex items-center gap-1 text-ink">
                <Accessibility className="size-3.5" aria-hidden />
                {t('stepFree')}
              </span>
            )}
          </p>
        </div>
        <p className="shrink-0 text-right">
          <span className="block text-xs text-ink-muted">{t('arrival')}</span>
          <span className="tabular text-lg leading-tight font-semibold tracking-heading">
            {arrival}
          </span>
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onStart}
          className="flex h-10 min-w-0 flex-1 items-center justify-center gap-2 rounded-control bg-route text-md font-medium text-on-route shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_6px_16px_-8px_var(--route)] transition-[filter,transform] duration-150 ease-out-soft hover:brightness-110 active:scale-[0.985]"
        >
          <Play className="size-3.5 fill-current" aria-hidden />
          {t('startWalk')}
        </button>
        <CopyLinkButton link={link} />
      </div>
    </div>
  );
}

function Steps({
  route,
  origin,
  destination,
  reducedMotion,
}: {
  route: RouteResponse;
  origin: string;
  destination: string;
  reducedMotion: boolean;
}) {
  const t = useTranslations('Route');
  const turns = useTranslations('Turns');
  const compass = useTranslations('Compass');
  const locale = useLocale() as Locale;
  const { activeStep, setActiveStep } = useRouteStore();
  const graph = useCampusGraph();
  const { steps } = route;

  // Each thumbnail looks the way the visitor walks from that spot (on
  // arrival: the way they came in), the same view the 360° inset opens on.
  const faces = useMemo(() => {
    const byId = graph.data?.byId;
    return steps.map((step): CubeFace => {
      const node = byId?.get(step.node_id);
      const at = route.node_ids.indexOf(step.node_id);
      const next = byId?.get(route.node_ids[at + 1] ?? '');
      const previous = byId?.get(route.node_ids[at - 1] ?? '');
      if (!node) return 'f';
      const [a, b] = next ? [node, next] : previous ? [previous, node] : [];
      if (!a || !b) return 'f';
      return faceTowards(
        bearingDeg([a.enu[0], a.enu[1]], [b.enu[0], b.enu[1]]),
        node.heading_deg,
      );
    });
  }, [graph.data, route.node_ids, steps]);

  const instruction = (step: RouteStep) =>
    step.turn === 'arrive'
      ? turns('arrive', { place: destination })
      : step.turn === 'start'
        ? turns('start', {
            direction: compass(String(compassIndex(step.bearing_deg)) as '0'),
          })
        : turns(step.turn);

  return (
    <ol
      aria-label={t('steps')}
      className="relative -mx-2 flex flex-col border-t border-hairline pt-2"
    >
      {steps.map((step, index) => {
        const active = index === activeStep;
        const arrive = step.turn === 'arrive';
        const start = index === 0;
        const last = index === steps.length - 1;
        const distance =
          step.distance_m > 0 ? formatDistance(step.distance_m, locale) : '';
        const text = instruction(step);
        const meta = start ? origin : distance;
        return (
          <motion.li
            key={`${step.node_id}-${index}`}
            className="relative"
            initial={reducedMotion ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.06 + Math.min(index, 8) * 0.03,
              duration: 0.2,
              ease: EASE,
            }}
          >
            {!last && (
              <span
                aria-hidden
                className="absolute top-1/2 left-[21px] h-full w-0.5 rounded-full bg-route/25"
              />
            )}
            <button
              type="button"
              onClick={() => setActiveStep(active ? undefined : index)}
              aria-current={active ? 'step' : undefined}
              aria-label={`${text}${distance ? `, ${distance}` : ''}. ${t('previewStep')}`}
              title={t('previewStep')}
              className={cn(
                'group relative grid min-h-14 w-full grid-cols-[1.75rem_1fr_auto] items-center gap-x-3 rounded-[12px] py-1.5 pr-1.5 pl-2 text-left',
                'transition-colors duration-150 ease-out-soft',
                active ? 'bg-route-soft' : 'hover:bg-fill',
              )}
            >
              <span className="flex justify-center">
                {start && !active ? (
                  <span className="flex size-7 items-center justify-center">
                    <span className="size-3.5 rounded-full border-[3.5px] border-route bg-stone-raised shadow-[0_0_0_3px_var(--stone-raised)]" />
                  </span>
                ) : (
                  <span
                    className={cn(
                      'flex size-7 items-center justify-center rounded-full transition-colors duration-150',
                      arrive
                        ? 'bg-brick text-white'
                        : active
                          ? 'bg-route text-on-route'
                          : 'bg-stone-raised text-route shadow-[inset_0_0_0_1px_var(--hairline)]',
                    )}
                  >
                    <StepIcon turn={step.turn} className="size-3.5" />
                  </span>
                )}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="text-md leading-snug font-medium">{text}</span>
                {meta && (
                  <span className="tabular truncate text-xs text-ink-muted">
                    {meta}
                  </span>
                )}
              </span>
              <PanoThumb
                scene={step.node_id}
                face={faces[index]}
                className={cn(
                  'h-10 w-15 rounded-[8px] transition-shadow duration-150',
                  active && 'shadow-[0_0_0_2px_var(--route)]',
                )}
              >
                <span
                  aria-hidden
                  className="absolute right-1 bottom-1 rounded-[4px] bg-black/50 px-1 text-[10px] leading-[14px] font-semibold text-white backdrop-blur-sm"
                >
                  360°
                </span>
              </PanoThumb>
            </button>
          </motion.li>
        );
      })}
    </ol>
  );
}

function RouteSkeleton() {
  return (
    <div className="flex flex-col gap-3.5 pt-1" aria-hidden>
      <div className="flex items-end justify-between">
        <div className="flex flex-col gap-2">
          <span className="h-8 w-20 animate-shimmer rounded-md bg-fill-strong" />
          <span className="h-3.5 w-28 animate-shimmer rounded bg-fill" />
        </div>
        <span className="h-9 w-14 animate-shimmer rounded-md bg-fill" />
      </div>
      <span className="h-10 animate-shimmer rounded-control bg-route/15" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-3 px-0.5">
          <span className="size-7 animate-shimmer rounded-full bg-fill-strong" />
          <span className="h-4 flex-1 animate-shimmer rounded bg-fill" />
          <span className="h-10 w-15 animate-shimmer rounded-[8px] bg-fill" />
        </div>
      ))}
    </div>
  );
}
