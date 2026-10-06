'use client';

import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { FanMark } from '@/components/brand/FanMark';
import { Glass } from '@/components/glass/Glass';
import { TooltipProvider } from '@/components/ui/tooltip';
import { compassIndex } from '@/features/campus/coords';
import {
  useBuildings,
  useCampusGraph,
  useGreenery,
  useGround,
  useRoute,
} from '@/features/campus/queries';
import type { GraphNode } from '@/features/campus/types';
import {
  useNow,
  useSky,
  useThemeFromSky,
  useWeather,
} from '@/features/environment/hooks';
import { StatusPill } from '@/features/environment/StatusPill';
import {
  atCampusHour,
  useEnvironmentStore,
} from '@/features/environment/store';
import { conditionOf } from '@/features/environment/weather';
import { PanoInset, type PanoStep } from '@/features/pano/PanoInset';
import { DirectionsPanel } from '@/features/route/DirectionsPanel';
import { StepIcon } from '@/features/route/StepIcon';
import { useRouteStore } from '@/features/route/store';
import { Link, usePathname } from '@/i18n/navigation';
import { formatDistance, type Locale } from '@/lib/format';

import { MapControls } from './MapControls';
import { MapOverlays } from './MapOverlays';

// WebGL only exists in the browser.
const CampusScene = dynamic(
  () => import('@/features/campus/CampusScene').then((m) => m.CampusScene),
  { ssr: false },
);

const EASE = [0.2, 0.7, 0.2, 1] as const;

export function MapApp() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const reducedMotion = useReducedMotion() ?? false;
  const graph = useCampusGraph();
  const buildings = useBuildings();
  const greenery = useGreenery();
  const ground = useGround();
  const weather = useWeather();
  const live = useNow();
  const preview = useEnvironmentStore();
  const now = useMemo(
    () =>
      preview.hour === undefined ? live : atCampusHour(live, preview.hour),
    [live, preview.hour],
  );
  const sky = useSky(now);
  useThemeFromSky(sky.phase);

  const {
    from,
    to,
    avoidStairs,
    activeStep,
    exploreNodeId,
    setActiveStep,
    setExploreNode,
  } = useRouteStore();
  const route = useRoute(from?.id, to?.id, avoidStairs);
  const routeData = route.isError ? undefined : route.data;

  const steps = routeData?.steps ?? [];
  const step = activeStep !== undefined ? steps[activeStep] : undefined;
  const stepNode = step ? graph.data?.byId.get(step.node_id) : undefined;
  const nextNodeId =
    step && routeData
      ? routeData.node_ids[routeData.node_ids.indexOf(step.node_id) + 1]
      : undefined;
  const nextNode = nextNodeId ? graph.data?.byId.get(nextNodeId) : undefined;
  const exploreNode = exploreNodeId
    ? graph.data?.byId.get(exploreNodeId)
    : undefined;
  const panoNode = stepNode ?? exploreNode;
  const routeNodes = useMemo(
    () =>
      (routeData?.node_ids ?? [])
        .map((id) => graph.data?.byId.get(id))
        .filter((n): n is GraphNode => !!n),
    [routeData, graph.data],
  );

  const nodeLabel = useCallback(
    (node: GraphNode) => (locale === 'en' ? node.label.en : node.label.tr),
    [locale],
  );
  const panoStep: PanoStep | undefined =
    step && activeStep !== undefined
      ? {
          index: activeStep,
          count: steps.length,
          icon: <StepIcon turn={step.turn} className="size-4.5" />,
          instruction:
            step.turn === 'arrive'
              ? t('Turns.arrive', { place: to?.name ?? '' })
              : step.turn === 'start'
                ? t('Turns.start', {
                    direction: t(
                      `Compass.${String(compassIndex(step.bearing_deg)) as '0'}`,
                    ),
                  })
                : t(`Turns.${step.turn}`),
          distance:
            step.distance_m > 0
              ? formatDistance(step.distance_m, locale)
              : undefined,
        }
      : undefined;

  const closePano = useCallback(() => {
    setActiveStep(undefined);
    setExploreNode(undefined);
  }, [setActiveStep, setExploreNode]);

  // Keyboard: Escape closes the 360° view, arrows walk through the steps.
  useEffect(() => {
    if (!panoNode) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [role="combobox"]')) return;
      if (event.key === 'Escape') closePano();
      if (activeStep === undefined) return;
      if (event.key === 'ArrowRight' && activeStep < steps.length - 1)
        setActiveStep(activeStep + 1);
      if (event.key === 'ArrowLeft' && activeStep > 0)
        setActiveStep(activeStep - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [panoNode, activeStep, steps.length, closePano, setActiveStep]);

  const ready = Boolean(graph.data && buildings.data);
  const viewportHeight = useViewportHeight();
  // Mirrors the layout below: panel = 24.5rem + 1rem margin; 360° view =
  // min(30rem, 58vh) + 2.25rem from the bottom.
  const insets = useMemo(
    () => ({
      left: 408,
      bottom: panoNode ? Math.min(480, viewportHeight * 0.58) + 36 : 0,
    }),
    [panoNode, viewportHeight],
  );
  const condition =
    preview.condition ??
    (weather.data ? conditionOf(weather.data.weather_code) : undefined);

  return (
    <TooltipProvider delay={350}>
      <div className="relative h-dvh w-full overflow-hidden bg-stone">
        <div className="absolute inset-0">
          {graph.data && (
            <CampusScene
              graph={graph.data}
              buildings={buildings.data ?? []}
              greenery={greenery.data}
              ground={ground.data}
              routeNodeIds={routeData?.node_ids}
              activeNodeId={stepNode?.id}
              exploreNodeId={exploreNode?.id}
              sky={sky}
              condition={condition}
              insets={insets}
              reducedMotion={reducedMotion}
            />
          )}
        </div>
        {graph.data && ready && (
          <MapOverlays
            nodes={graph.data.nodes}
            buildings={buildings.data ?? []}
            route={routeNodes}
            focusNodeId={panoNode?.id}
            destinationLabel={to?.name}
            labelOf={nodeLabel}
            onOpenPano={(node) => setExploreNode(node.id)}
          />
        )}

        <AnimatePresence>
          {!ready && !graph.isError && (
            <motion.div
              key="splash"
              className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-4 bg-stone"
              exit={{ opacity: 0 }}
              transition={{ duration: 0.4, ease: EASE }}
            >
              <FanMark className="size-16 animate-fan text-ink" />
              <p className="font-display text-lg font-semibold">
                {t('Map.loading')}
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.aside
          className="pointer-events-none absolute top-4 bottom-4 left-4 z-10 flex w-[24.5rem] flex-col"
          initial={reducedMotion ? false : { opacity: 0, x: -16 }}
          animate={ready ? { opacity: 1, x: 0 } : undefined}
          transition={{ duration: 0.5, ease: EASE, delay: 0.15 }}
        >
          <Glass
            variant="thick"
            radius={28}
            refract={false}
            className="pointer-events-auto flex max-h-full min-h-0 flex-col"
          >
            <header className="flex items-center gap-3 px-5 pt-5 pb-4">
              <span className="flex size-10 items-center justify-center rounded-xl bg-ink text-stone-raised shadow-elevation-1">
                <FanMark className="size-6" />
              </span>
              <div className="min-w-0">
                <h1 className="font-display text-xl leading-none font-bold">
                  {t('Brand.name')}
                </h1>
                <p className="mt-1 text-xs text-ink-muted">
                  {t('Brand.campus')}
                </p>
              </div>
            </header>
            <div className="min-h-0 flex-1 [scrollbar-width:thin] overflow-y-auto overscroll-contain px-4 pb-4">
              {graph.isError ? (
                <p className="rounded-2xl bg-brick/10 p-4 text-sm">
                  {t('Route.apiDown')}
                </p>
              ) : (
                <DirectionsPanel
                  route={routeData}
                  error={route.error ?? undefined}
                  loading={route.isFetching}
                  now={now}
                  reducedMotion={reducedMotion}
                />
              )}
            </div>
          </Glass>
        </motion.aside>

        <motion.div
          className="pointer-events-none absolute top-4 right-4 z-10 flex items-center gap-2"
          initial={reducedMotion ? false : { opacity: 0, y: -10 }}
          animate={ready ? { opacity: 1, y: 0 } : undefined}
          transition={{ duration: 0.5, ease: EASE, delay: 0.25 }}
        >
          <div className="pointer-events-auto">
            <StatusPill
              now={now}
              live={live}
              sky={sky}
              weather={weather.data}
              condition={condition}
              weatherError={weather.isError}
            />
          </div>
          <LanguageSwitch />
        </motion.div>

        <motion.div
          className="pointer-events-none absolute top-1/2 right-4 z-10 -translate-y-1/2"
          initial={reducedMotion ? false : { opacity: 0, x: 10 }}
          animate={ready ? { opacity: 1, x: 0 } : undefined}
          transition={{ duration: 0.5, ease: EASE, delay: 0.3 }}
        >
          <MapControls reducedMotion={reducedMotion} />
        </motion.div>

        <AnimatePresence>
          {panoNode && (
            <motion.div
              key="pano"
              className="absolute right-20 bottom-9 z-20 h-[min(30rem,58vh)] w-[min(46rem,calc(100vw-33rem))]"
              initial={
                reducedMotion ? false : { opacity: 0, y: 24, scale: 0.97 }
              }
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={
                reducedMotion
                  ? { opacity: 0 }
                  : { opacity: 0, y: 16, scale: 0.98 }
              }
              transition={{ duration: 0.3, ease: EASE }}
            >
              <PanoInset
                node={panoNode}
                next={stepNode ? nextNode : undefined}
                title={nodeLabel(panoNode)}
                step={panoStep}
                night={sky.phase === 'night' || sky.phase === 'twilight'}
                reducedMotion={reducedMotion}
                onClose={closePano}
                onStep={(index) => setActiveStep(index)}
                onPrevious={
                  activeStep !== undefined && activeStep > 0
                    ? () => setActiveStep(activeStep - 1)
                    : undefined
                }
                onNext={
                  activeStep !== undefined && activeStep < steps.length - 1
                    ? () => setActiveStep(activeStep + 1)
                    : undefined
                }
              />
            </motion.div>
          )}
        </AnimatePresence>

        <footer className="pointer-events-auto absolute right-4 bottom-2 z-10 flex gap-3 text-[11px] text-ink-muted [text-shadow:0_0_6px_var(--stone)]">
          <span>{t('Attribution.imagery')}</span>
          <span>{t('Attribution.map')}</span>
          <span>{t('Attribution.weather')}</span>
          <span>{t('Brand.independent')}</span>
        </footer>
      </div>
    </TooltipProvider>
  );
}

function useViewportHeight(): number {
  const [height, setHeight] = useState(800);
  useEffect(() => {
    const update = () => setHeight(window.innerHeight);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return height;
}

function LanguageSwitch() {
  const t = useTranslations('Language');
  const locale = useLocale();
  const pathname = usePathname();
  return (
    <Glass
      as="nav"
      radius={999}
      aria-label={t('label')}
      className="pointer-events-auto flex h-11 items-center p-1"
    >
      {(['tr', 'en'] as const).map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          aria-current={l === locale ? 'true' : undefined}
          title={t(l)}
          className={[
            'flex h-9 min-w-10 items-center justify-center rounded-full px-2 font-display text-sm font-bold transition-colors duration-150 ease-out-soft',
            l === locale
              ? 'bg-ink text-stone-raised'
              : 'text-ink-muted hover:text-ink',
          ].join(' ')}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </Glass>
  );
}
