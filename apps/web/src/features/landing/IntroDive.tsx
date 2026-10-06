'use client';

import Lenis from 'lenis';
import { AnimatePresence, motion } from 'motion/react';
import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import { FanMark } from '@/components/brand/FanMark';
import { useNow, useSky, useWeather } from '@/features/environment/hooks';
import { Link, usePathname } from '@/i18n/navigation';
import { assetBaseUrl } from '@/lib/assets';

import { stageAt } from './cameraPath';
import { useEarth } from './earth';
import type { Credit } from './GoogleTiles';
import { landingState } from './state';

const LandingScene = dynamic(
  () => import('./LandingScene').then((m) => m.LandingScene),
  { ssr: false },
);

const noSubscription = () => () => {};
const GOOGLE_LOGO =
  'https://maps.gstatic.com/mapfiles/api-3/images/google_white5.png';
const HEADINGS = ['title', 'stage1', 'stage2', 'stage3'] as const;
const BODIES = [
  'stage0Body',
  'stage1Body',
  'stage2Body',
  'stage3Body',
] as const;
const EASE = [0.2, 0.7, 0.2, 1] as const;
/** Scroll length of the dive, in viewport heights. */
const DIVE_VH = 360;
const CLOUD_BASE_M = 2700;
const CLOUD_TOP_M = 3050;
/** Past this share of the scroll the dive finishes by itself. */
const FINISH_AT = 0.97;
const FADE_MS = 1100;

type Phase = 'diving' | 'landing' | 'gone';

/**
 * The opening dive over İstanbul, laid over the map. Scrolling flies the
 * camera from 30 km down to the map's own opening pose; near the end the
 * dive completes by itself and dissolves into the map underneath, which is
 * already loaded and waiting in the same pose. No page change, no button.
 */
export function IntroDive({
  onReveal,
  onDone,
}: {
  /** The fade into the map starts: the map's chrome can come in. */
  onReveal: () => void;
  /** The fade has run: the dive can be unmounted. */
  onDone: () => void;
}) {
  const t = useTranslations('Landing');
  const locale = useLocale();
  const now = useNow();
  // ?hour=21 previews another time of day (QA and screenshots).
  const previewHour = useSyncExternalStore(
    noSubscription,
    () => new URLSearchParams(window.location.search).get('hour'),
    () => null,
  );
  const skyTime = useMemo(() => {
    const hour = previewHour === null ? NaN : Number(previewHour);
    if (!Number.isFinite(hour)) return now;
    const at = new Date(now);
    at.setHours(Math.floor(hour), Math.round((hour % 1) * 60), 0, 0);
    return at;
  }, [now, previewHour]);
  const sky = useSky(skyTime);
  const weather = useWeather();
  const earth = useEarth(`${assetBaseUrl}/earth`);
  const [stage, setStage] = useState(0);
  const [credits, setCredits] = useState<Credit[]>();
  const [phase, setPhase] = useState<Phase>('diving');
  const photoreal = Boolean(process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN);
  const [firstView, setFirstView] = useState(!photoreal);
  useEffect(() => {
    if (firstView) return;
    // Never hold the curtain for long: after a few seconds show what we have.
    const timer = setTimeout(() => setFirstView(true), 7000);
    return () => clearTimeout(timer);
  }, [firstView]);

  const wrapper = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const whiteout = useRef<HTMLDivElement>(null);
  const hint = useRef<HTMLDivElement>(null);
  const pin = useRef<HTMLDivElement>(null);
  const lenis = useRef<Lenis | null>(null);

  // Play the rest of the dive by itself (skip, or the end of the scroll).
  const finish = useCallback(() => {
    const scroller = lenis.current;
    if (!scroller) return;
    setPhase((p) => (p === 'diving' ? 'landing' : p));
    scroller.scrollTo(scroller.limit, {
      duration: 2.2 * (1 - scroller.progress) + 0.6,
      easing: (x) => 1 - (1 - x) ** 3,
      lock: true,
      force: true,
    });
  }, []);

  useEffect(() => {
    const el = wrapper.current;
    const inner = content.current;
    if (!el || !inner) return;
    landingState.target = 0;
    landingState.progress = 0;
    const scroller = new Lenis({
      wrapper: el,
      content: inner,
      autoRaf: true,
      lerp: 0.085,
      wheelMultiplier: 0.9,
      touchMultiplier: 1.4,
    });
    lenis.current = scroller;
    el.focus({ preventScroll: true });
    let finishing = false;
    scroller.on('scroll', () => {
      landingState.target = scroller.progress;
      if (!finishing && scroller.progress >= FINISH_AT) {
        finishing = true;
        finish();
      }
    });
    let frame = 0;
    const tick = () => {
      const p = landingState.progress;
      const next = stageAt(p);
      setStage((s) => (s === next ? s : next));
      // Flying through the cloud deck whites the view out, briefly.
      const alt = landingState.altitude;
      const mid = (CLOUD_BASE_M + CLOUD_TOP_M) / 2;
      const inside =
        1 - Math.min(1, Math.max(0, Math.abs(alt - mid) - 40) / 240);
      if (whiteout.current)
        whiteout.current.style.opacity = String(inside * 0.7);
      if (hint.current)
        hint.current.style.opacity = String(Math.max(0, 1 - p * 12));
      const pinEl = pin.current;
      if (pinEl) {
        const { x, y, visible } = landingState.campus;
        const show = visible ? Math.min(1, Math.max(0, (p - 0.8) / 0.08)) : 0;
        pinEl.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
        pinEl.style.opacity = String(show);
      }
      // Arrived: the camera sits in the map's pose, so dissolve into it.
      if (p > 0.996) setPhase((ph) => (ph === 'gone' ? ph : 'gone'));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      scroller.destroy();
      lenis.current = null;
    };
  }, [finish]);

  // Hand over: the map's chrome comes in with the fade, and the dive (its
  // tiles and GL context) is released afterwards, when the browser is idle,
  // so the two never land on the same frame.
  useEffect(() => {
    if (phase !== 'gone') return;
    onReveal();
    let idle = 0;
    const timer = setTimeout(() => {
      idle = window.requestIdleCallback
        ? window.requestIdleCallback(onDone, { timeout: 800 })
        : window.setTimeout(onDone, 0);
    }, FADE_MS);
    return () => {
      clearTimeout(timer);
      if (idle && window.cancelIdleCallback) window.cancelIdleCallback(idle);
    };
  }, [phase, onReveal, onDone]);

  const temperature = weather.data?.temperature_c;
  const time = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Istanbul',
  }).format(now);
  const gone = phase === 'gone';

  return (
    <div
      className="fixed inset-0 z-40 bg-[#0b1220] text-white transition-opacity ease-out"
      style={{
        opacity: gone ? 0 : 1,
        transitionDuration: `${FADE_MS}ms`,
        pointerEvents: gone ? 'none' : undefined,
      }}
    >
      <div className="absolute inset-0" aria-hidden>
        <LandingScene
          earth={earth}
          sky={sky}
          reducedMotion={false}
          photorealToken={process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN || undefined}
          onCredits={setCredits}
          onFirstView={() => setFirstView(true)}
          // The deck follows today's sky over Florya.
          cloudCoverage={
            weather.data
              ? 0.1 + (weather.data.cloud_cover_pct / 100) * 0.22
              : 0.24
          }
        />
        {/* Legibility: a soft scrim under the captions, nothing else. */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_0%_100%,rgb(5_10_20/0.55),transparent_60%)]" />
        <div
          ref={pin}
          className="pointer-events-none absolute top-0 left-0 opacity-0"
        >
          <div className="flex -translate-x-[9px] -translate-y-1/2 items-center gap-2">
            <span className="relative flex size-[18px] items-center justify-center">
              <span className="absolute inset-0 animate-ping-soft rounded-full bg-ochre/70" />
              <span className="relative size-3.5 rounded-full border-[3px] border-white bg-ochre shadow-[0_2px_8px_rgb(0_0_0/0.4)]" />
            </span>
            <span className="rounded-full bg-[rgb(10_16_28/0.6)] px-3 py-1 text-[13px] font-semibold whitespace-nowrap text-white ring-1 ring-white/20 backdrop-blur-md">
              {t('pin')}
            </span>
          </div>
        </div>
        <div
          ref={whiteout}
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgb(255_255_255/0.95),rgb(226_234_242/0.85))] opacity-0"
        />
        {/* Opening curtain until the first sharp view of the city is in. */}
        <div
          className={[
            'pointer-events-none absolute inset-0 flex items-center justify-center bg-[#0b1220] transition-opacity duration-[1400ms] ease-out',
            firstView ? 'opacity-0' : 'opacity-100',
          ].join(' ')}
        >
          <FanMark className="size-10 animate-fan text-white/80" />
        </div>
      </div>

      {/* The scroll track that drives the dive (its own scroller). */}
      <div
        ref={wrapper}
        tabIndex={-1}
        className="absolute inset-0 [scrollbar-width:none] overflow-y-auto overscroll-contain outline-none [&::-webkit-scrollbar]:hidden"
      >
        <div ref={content} style={{ height: `${DIVE_VH}vh` }} />
      </div>

      <header className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-between px-5 py-4 sm:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-[10px] bg-white/12 ring-1 ring-white/20 backdrop-blur-md">
            <FanMark className="size-4.5 text-white" />
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.01em]">
            Aydın Kampüs
          </span>
        </div>
        <div className="pointer-events-auto flex items-center gap-2">
          <span className="hidden rounded-full bg-white/12 px-3 py-1.5 text-sm tabular-nums ring-1 ring-white/20 backdrop-blur-md sm:inline">
            {time}
            {temperature !== undefined && (
              <span className="ml-2 border-l border-white/25 pl-2">
                {Math.round(temperature)}°
              </span>
            )}
          </span>
          <LocaleLink />
          <button
            type="button"
            onClick={finish}
            className="rounded-full bg-white px-3.5 py-1.5 text-sm font-medium text-[#0b1220] transition-colors hover:bg-white/90"
          >
            {t('skipDive')}
          </button>
        </div>
      </header>

      <section
        aria-live="polite"
        className="pointer-events-none absolute bottom-0 left-0 z-10 max-w-[38rem] px-5 pb-16 sm:px-10 sm:pb-14"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={stage}
            initial={{ opacity: 0, y: 14, filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -10, filter: 'blur(6px)' }}
            transition={{ duration: 0.6, ease: EASE }}
          >
            {stage === 0 ? (
              <h1 className="text-[clamp(2.1rem,5.2vw,3.6rem)] leading-[1.02] font-semibold tracking-[-0.03em] text-balance">
                {t('title')}
              </h1>
            ) : (
              <h2 className="text-[clamp(1.7rem,4vw,2.8rem)] leading-[1.05] font-semibold tracking-[-0.025em] text-balance">
                {t(HEADINGS[stage] ?? 'stage3')}
              </h2>
            )}
            <p className="mt-3 max-w-[32rem] text-[17px] leading-relaxed text-white/80">
              {t(BODIES[stage] ?? 'stage3Body')}
            </p>
          </motion.div>
        </AnimatePresence>
      </section>

      <div
        ref={hint}
        className="pointer-events-none absolute right-0 bottom-10 left-0 z-10 hidden justify-center text-sm text-white/75 sm:flex"
      >
        <span className="flex flex-col items-center gap-2">
          {t('scroll')}
          <span className="block h-8 w-px animate-pulse bg-white/60" />
        </span>
      </div>

      <footer className="pointer-events-auto absolute right-0 bottom-0 z-10 flex max-w-[46rem] items-center justify-end gap-2 px-5 pb-3 text-right text-[11px] leading-snug text-white/70 sm:px-8">
        {credits && credits.length > 0 ? (
          <>
            {/* Google's attribution rules: its logo plus the data credits. */}
            {/* eslint-disable-next-line @next/next/no-img-element -- Google's own logo asset */}
            <img
              src={GOOGLE_LOGO}
              alt="Google"
              className="h-[14px] w-auto opacity-90"
            />
            <span>
              {credits
                .filter((c) => c.text)
                .map((c) => c.text)
                .join(' · ')}
              {' · '}
              <a
                href="https://cesium.com/platform/cesium-ion/"
                target="_blank"
                rel="noreferrer"
                className="underline-offset-2 hover:underline"
              >
                Cesium ion
              </a>
            </span>
          </>
        ) : (
          <span>
            {(earth?.manifest.attribution ?? []).map((full, i) => (
              <span key={full} title={full}>
                {i > 0 && ' · '}
                {shortCredit(full)}
              </span>
            ))}
          </span>
        )}
      </footer>
    </div>
  );
}

/**
 * Compact credit labels; the full required text stays in the tooltip. EOX's
 * licence asks for its exact string, so it is shown as is.
 */
function shortCredit(full: string): string {
  if (full.startsWith('EOxCloudless')) return full;
  if (full.includes('Black Marble')) return 'NASA Black Marble';
  if (full.startsWith('Terrain Tiles'))
    return 'Terrain Tiles (Mapzen/Tilezen, USGS)';
  if (full.includes('OpenStreetMap')) return '© OpenStreetMap';
  return full;
}

function LocaleLink() {
  const locale = useLocale();
  const pathname = usePathname();
  const other = locale === 'en' ? 'tr' : 'en';
  return (
    <Link
      href={pathname}
      locale={other}
      className="rounded-full bg-white/12 px-3 py-1.5 text-sm font-medium uppercase ring-1 ring-white/20 backdrop-blur-md transition-colors hover:bg-white/20"
    >
      {other}
    </Link>
  );
}
