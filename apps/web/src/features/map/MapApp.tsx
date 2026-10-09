'use client';

import { cn } from 'cn';
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useReducedMotion,
} from 'motion/react';
import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import { Info, MessageCircle, Navigation } from 'lucide-react';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useShallow } from 'zustand/react/shallow';

import { FanMark } from '@/components/brand/FanMark';
import { Glass } from '@/components/glass/Glass';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  type Place,
  useBuildings,
  useCampusGraph,
  useGreenery,
  useGround,
  usePlaceDirectory,
  useRoute,
} from '@/features/campus/queries';
import type { Credit } from '@/features/campus/GoogleTiles';
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
import type { PanoStep } from '@/features/pano/PanoInset';
import { DirectionsPanel } from '@/features/route/DirectionsPanel';
import {
  gapDoors,
  isIndoorSpot,
  routeMapIds,
  routeMatchesGraph,
  routeParts,
  shownFloor,
  viewYaw,
  whereText,
} from '@/features/route/indoor';
import { isPinnedPoi, pinnedSpots, SAME_SPOT_M } from '@/features/route/places';
import { RouteUrlSync } from '@/features/route/RouteUrlSync';
import { StepIcon } from '@/features/route/StepIcon';
import {
  isIndoorStep,
  stepDistance,
  useStepText,
} from '@/features/route/stepText';
import { type PanelTab, useRouteStore } from '@/features/route/store';
import { routeParamsOf, withRouteParams } from '@/features/route/urlState';
import { Link, usePathname } from '@/i18n/navigation';
import {
  formatDistance,
  formatFloor,
  type Locale,
  sentenceCase,
} from '@/lib/format';

import { useCameraStore } from './cameraStore';
import { MapControls } from './MapControls';
import { MapOverlays } from './MapOverlays';
import { PanelShell } from './PanelShell';
import { usePoiWhere } from './PoiLayer';
import { coveredHeight, type SheetSnap, snapHeights } from './sheet';

// WebGL only exists in the browser.
const CampusScene = dynamic(
  () => import('@/features/campus/CampusScene').then((m) => m.CampusScene),
  { ssr: false },
);
// Not needed for the first paint, and heavy: the 360° viewer
// (photo-sphere-viewer) and the assistant (AI SDK). Each loads as its own
// chunk.
const PanoInset = dynamic(
  () => import('@/features/pano/PanoInset').then((m) => m.PanoInset),
  { ssr: false },
);
const AssistantPanel = dynamic(
  () => import('@/features/chat/AssistantPanel').then((m) => m.AssistantPanel),
  { ssr: false },
);

const EASE = [0.2, 0.7, 0.2, 1] as const;
const TABS: readonly PanelTab[] = ['directions', 'assistant'];

/** Tailwind's `md`: from here the panel floats on the left, below it docks at the bottom. */
const DESKTOP_PX = 768;
/** Panel: 23.25rem wide, 0.75rem from the edge (keep in sync with PanelShell). */
const PANEL_EDGE_PX = 372 + 12;
/**
 * Mobile map controls end here: 3.5rem from the top, three 36 px buttons and
 * a divider (keep in sync with the classes below and MapControls). Below this
 * much uncovered map they would collide with the sheet, so they step aside.
 */
const MOBILE_CONTROLS_BOTTOM_PX = 56 + 3 * 36 + 9 + 12;

const PHOTOREAL_TOKEN = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN || undefined;

/** The map's chrome never waits longer than this for the opening. */
const OPENING_DEADLINE_MS = 12_000;

/** The opening plays once per browser session (and never over a shared route). */
const OPENING_SEEN_KEY = 'amap.opening.seen';

function openingSkipped(): boolean {
  if (typeof window === 'undefined') return false;
  const search = new URLSearchParams(window.location.search);
  if (search.has('from') || search.has('to')) return true;
  try {
    return window.sessionStorage.getItem(OPENING_SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function markOpeningSeen() {
  try {
    window.sessionStorage.setItem(OPENING_SEEN_KEY, '1');
  } catch {
    // Storage may be blocked; the opening then plays on every visit.
  }
}

/**
 * `opening`: build the campus out of a dot map (CampusScene) before the map's
 * chrome comes in.
 */
export function MapApp({ opening = false }: { opening?: boolean }) {
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

  const directory = usePlaceDirectory();
  const poiWhere = usePoiWhere();
  const {
    from,
    to,
    avoidStairs,
    activeStep,
    exploreNodeId,
    setTo,
    setActiveStep,
    setExploreNode,
  } = useRouteStore();
  const route = useRoute(from?.id, to?.id, avoidStairs);
  // In the store, so `?panel=assistant` (e.g. a shared link)
  // opens the assistant and the tab survives a language switch.
  const panelTab = useRouteStore((s) => s.panel);
  const setPanelTab = useRouteStore((s) => s.setPanel);
  const routeData = route.isError ? undefined : route.data;

  const steps = routeData?.steps ?? [];
  const step = activeStep !== undefined ? steps[activeStep] : undefined;
  const stepNode = step ? graph.data?.byId.get(step.node_id) : undefined;
  const nextNodeId =
    step && routeData
      ? routeData.node_ids[routeData.node_ids.indexOf(step.node_id) + 1]
      : undefined;
  const nextNode = nextNodeId ? graph.data?.byId.get(nextNodeId) : undefined;
  const previousNodeId =
    step && routeData
      ? routeData.node_ids[routeData.node_ids.indexOf(step.node_id) - 1]
      : undefined;
  const previousNode = previousNodeId
    ? graph.data?.byId.get(previousNodeId)
    : undefined;
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
  // A route over a node or hop the map's graph lacks: one side loaded the
  // graph before a new one was published. Fetch both again, once per route.
  const resynced = useRef<string | undefined>(undefined);
  const refetchGraph = graph.refetch;
  const refetchRoute = route.refetch;
  useEffect(() => {
    if (!routeData || !graph.data) return;
    const key = routeData.node_ids.join(',');
    if (resynced.current === key) return;
    if (routeMatchesGraph(routeData.node_ids, graph.data)) return;
    resynced.current = key;
    void refetchGraph().then(() => refetchRoute());
  }, [routeData, graph.data, refetchGraph, refetchRoute]);
  // Indoor spots stand at the entrance they hang off: the map draws and
  // pins measured nodes only, and puts indoor ones on their entrance.
  const parts = useMemo(
    () => (graph.data ? routeParts(routeNodes, graph.data) : []),
    [routeNodes, graph.data],
  );
  const drawn = useMemo(() => parts.flat(), [parts]);
  // A business is pinned where its pin stands (its storefront, or its
  // building's door), not on its panorama's node (indoors only a borrowed
  // position).
  const toPlace = useMemo(
    () => (to ? directory.data?.find((p) => p.id === to.id) : undefined),
    [to, directory.data],
  );
  const destinationEnu =
    toPlace && isPinnedPoi(toPlace) ? toPlace.pin_enu : undefined;
  const routeExtent = useMemo(
    () => (toPlace && isPinnedPoi(toPlace) ? [toPlace.pin_enu] : undefined),
    [toPlace],
  );
  // Walking into such a business, the line ends at the door it goes in by;
  // when that is not where the destination pin stands, it gets the door
  // marker.
  const lastDrawn = drawn[drawn.length - 1];
  const entryDoor =
    destinationEnu &&
    lastDrawn &&
    isIndoorSpot(routeNodes[routeNodes.length - 1]) &&
    Math.hypot(
      lastDrawn.enu[0] - destinationEnu[0],
      lastDrawn.enu[1] - destinationEnu[1],
    ) >= SAME_SPOT_M
      ? lastDrawn
      : undefined;
  const doors = useMemo(() => {
    const gaps = gapDoors(parts);
    return entryDoor && !gaps.includes(entryDoor) ? [...gaps, entryDoor] : gaps;
  }, [parts, entryDoor]);
  // The camera frames everything the route covers, indoor spots on their
  // door; a route inside one building is that door (given twice: the scene
  // frames routes of two nodes or more).
  const frameIds = useMemo(() => {
    const ids = routeMapIds(routeNodes);
    return ids.length === 1 ? [ids[0]!, ids[0]!] : ids;
  }, [routeNodes]);
  const mapNodes = useMemo(
    () => graph.data?.nodes.filter((n) => !isIndoorSpot(n)) ?? [],
    [graph.data],
  );
  // A business's own indoor panoramas are shown at its pin.
  const pinOfSpot = useMemo(
    () =>
      pinnedSpots(directory.data ?? [], (id) =>
        isIndoorSpot(graph.data?.byId.get(id)),
      ),
    [directory.data, graph.data],
  );
  const toNode = to ? graph.data?.byId.get(to.id) : undefined;
  // The map's node for each: indoor spots sit on their entrance.
  const stepMapId = stepNode ? (stepNode.anchor ?? stepNode.id) : undefined;
  const panoMapId = panoNode ? (panoNode.anchor ?? panoNode.id) : undefined;
  const destinationMapId = toNode ? (toNode.anchor ?? toNode.id) : to?.id;
  // Indoors the pin says where. A business's pin says where it stands:
  // honestly at its building's door until its storefront is measured.
  const destinationWhere =
    destinationEnu && toPlace
      ? poiWhere(toPlace)
      : to && toNode && isIndoorSpot(toNode)
        ? (whereText(
            toNode,
            locale,
            toNode.label.tr,
            toNode.label.en,
            to.name,
          ) ?? t('Indoor.marker'))
        : undefined;
  const destinationLabel =
    to && destinationWhere
      ? t('Indoor.pin', { place: to.name, where: destinationWhere })
      : to?.name;
  const panoPin = panoNode ? pinOfSpot.get(panoNode.id) : undefined;
  // Indoors the 360° view faces the tour's hotspot towards the next spot.
  const panoYaw =
    stepNode &&
    graph.data &&
    [stepNode, nextNode, previousNode].some((n) => isIndoorSpot(n))
      ? viewYaw(graph.data, stepNode, nextNode, previousNode)
      : undefined;
  const stepText = useStepText();
  // The 360° header's floor, never one the step's own label contradicts.
  const stepFloorText = (s: NonNullable<typeof step>): string[] => {
    const floor = shownFloor(
      s.floor,
      s.place?.tr ?? '',
      s.place?.en ?? '',
      s.turn === 'arrive' ? (to?.name ?? '') : '',
    );
    return floor === undefined
      ? []
      : [sentenceCase(formatFloor(floor, locale), locale)];
  };

  const nodeLabel = useCallback(
    (node: GraphNode) => (locale === 'en' ? node.label.en : node.label.tr),
    [locale],
  );
  const panoStep: PanoStep | undefined =
    step && activeStep !== undefined
      ? {
          index: activeStep,
          count: steps.length,
          icon: <StepIcon turn={step.turn} className="size-4" />,
          instruction: stepText(step, to?.name ?? ''),
          // Indoors say where instead of an estimate (passages keep a ≈ one).
          distance: stepDistance(
            step,
            (m) => formatDistance(m, locale),
            (d) => t('Route.approxDistance', { distance: d }),
          ),
          detail: isIndoorStep(step)
            ? [t('Indoor.marker'), ...stepFloorText(step)].join(' · ')
            : undefined,
        }
      : undefined;

  const closePano = useCallback(() => {
    setActiveStep(undefined);
    setExploreNode(undefined);
  }, [setActiveStep, setExploreNode]);
  // Closing the 360° view gives focus back to whatever opened it.
  const panoOpener = useRef<HTMLElement | null>(null);
  const panoOpen = Boolean(panoNode);
  useEffect(() => {
    if (panoOpen) {
      panoOpener.current ??= document.activeElement as HTMLElement | null;
      return;
    }
    const opener = panoOpener.current;
    panoOpener.current = null;
    if (opener?.isConnected) opener.focus();
  }, [panoOpen]);

  // Keyboard: Escape closes the 360° view, arrows walk through the steps.
  useEffect(() => {
    if (!panoNode) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [role="combobox"], [role="tab"]'))
        return;
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

  // A shared link may name a step the route does not have (any more).
  useEffect(() => {
    if (routeData && activeStep !== undefined && !routeData.steps[activeStep])
      setActiveStep(undefined);
  }, [routeData, activeStep, setActiveStep]);

  // The opening plays over the map first (/), unless motion is reduced:
  // 'playing' -> 'reveal' (the chrome comes in) -> 'done'.
  // The client decides alone: before the data loads both look the same.
  const [introPhase, setIntroPhase] = useState<'playing' | 'reveal' | 'done'>(
    () => (opening && !openingSkipped() ? 'playing' : 'done'),
  );
  const playing = introPhase === 'playing' && !reducedMotion;
  const assembling = introPhase !== 'done' && !reducedMotion;
  const reveal = useCallback(() => {
    setIntroPhase('reveal');
    markOpeningSeen();
  }, []);
  // Last resort: the panel comes in this long after the data, whatever the
  // scene does (the opening itself ends after about 3 s).
  useEffect(() => {
    if (!assembling || !(graph.data && buildings.data)) return;
    const id = window.setTimeout(() => {
      reveal();
      setIntroPhase('done');
    }, OPENING_DEADLINE_MS);
    return () => window.clearTimeout(id);
  }, [assembling, graph.data, buildings.data, reveal]);
  const photoreal = useCameraStore((s) => s.photoreal);
  const [credits, setCredits] = useState<Credit[]>();
  const finishIntro = useCallback(() => setIntroPhase('done'), []);
  const dataReady = Boolean(graph.data && buildings.data);
  // The map's own chrome (panel, controls, labels) waits for the opening.
  const ready = dataReady && !playing;
  // Once the map is idle, warm the lazy chunks so the first 360° view or chat
  // opens at once.
  useEffect(() => {
    if (!ready || assembling) return;
    const warm = () => {
      void import('@/features/pano/PanoInset');
      void import('@/features/chat/AssistantPanel');
    };
    if (typeof requestIdleCallback === 'function') {
      const id = requestIdleCallback(warm, { timeout: 5000 });
      return () => cancelIdleCallback(id);
    }
    const id = window.setTimeout(warm, 1500);
    return () => window.clearTimeout(id);
  }, [ready, assembling]);
  const viewport = useViewport();
  const desktop = viewport.width >= DESKTOP_PX;
  const heights = useMemo(
    () => snapHeights(viewport.height),
    [viewport.height],
  );
  const [snap, setSnap] = useState<SheetSnap>('peek');
  const sheetCover = coveredHeight(heights[snap]);
  // A new route opens the sheet halfway: summary and first steps below, the
  // route itself on the map above.
  const routeKey = routeData?.node_ids.join();
  const [shownRoute, setShownRoute] = useState(routeKey);
  if (routeKey !== shownRoute) {
    setShownRoute(routeKey);
    if (routeKey) setSnap('half');
  }
  // On phones the 360° view covers the screen; everything else goes inert.
  const panoModal = !desktop && Boolean(panoNode);
  // Mirrors the layout below. Desktop: panel on the left, 360° view
  // min(30rem, 58vh) high, 2rem from the bottom. Mobile: the scene centres
  // above the sheet's snap, and its projection eases there as the sheet
  // springs, so the two move together.
  const panoHeight = Math.min(480, viewport.height * 0.58);
  const frameInsets = useMemo(
    () =>
      desktop
        ? { left: PANEL_EDGE_PX, bottom: panoNode ? panoHeight + 32 : 0 }
        : { left: 0, bottom: sheetCover },
    [desktop, panoNode, panoHeight, sheetCover],
  );
  // During the opening the view is centred on the whole screen; the panel's
  // offset eases in afterwards. The camera frames for the settled layout all
  // along, so the opening lands with the campus fitting the uncovered view.
  const insets = useMemo(
    () => (playing ? { left: 0, bottom: 0 } : frameInsets),
    [playing, frameInsets],
  );
  const controlsHidden =
    !desktop && viewport.height - sheetCover < MOBILE_CONTROLS_BOTTOM_PX;
  const attributionHidden = !desktop && snap === 'full';

  // Chrome above the sheet (the mobile credit line) follows it every frame
  // through a CSS variable, without re-rendering the map.
  const root = useRef<HTMLDivElement>(null);
  const setCovered = useCallback((px: number) => {
    root.current?.style.setProperty('--sheet-h', `${Math.round(px)}px`);
  }, []);

  // The chat needs room: opening it (by tab or by link) raises a peeking sheet.
  const [shownTab, setShownTab] = useState(panelTab);
  if (panelTab !== shownTab) {
    setShownTab(panelTab);
    if (panelTab === 'assistant' && snap === 'peek') setSnap('half');
  }
  // The assistant mounts on first open, then stays so a chat survives tab
  // switches.
  const [assistantMounted, setAssistantMounted] = useState(
    panelTab === 'assistant',
  );
  if (panelTab === 'assistant' && !assistantMounted) setAssistantMounted(true);
  const selectTab = (tab: PanelTab) => setPanelTab(tab);
  // A business pin on the map: the destination, as if picked in the search.
  const pickPlace = (place: Place) => {
    selectTab('directions');
    setTo({
      id: place.id,
      name: locale === 'en' ? place.name_en : place.name_tr,
    });
    // Phones: the sheet rises to show it and the start still to pick.
    if (!desktop && snap === 'peek') setSnap('half');
    // On to the start field, as from the search: keyboard and mouse only
    // (on a touch screen it would pop the keyboard up).
    if (!from && window.matchMedia('(pointer: fine)').matches)
      requestAnimationFrame(() =>
        document
          .querySelector<HTMLElement>('#panel-directions [role="combobox"]')
          ?.focus(),
      );
  };
  const condition =
    preview.condition ??
    (weather.data ? conditionOf(weather.data.weather_code) : undefined);

  const onTabKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const next = TABS[(TABS.indexOf(panelTab) + 1) % TABS.length] ?? panelTab;
    selectTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  };

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delay={350}>
        <div
          ref={root}
          className="relative h-dvh w-full overflow-hidden bg-stone"
        >
          {ready && (
            <button
              type="button"
              onClick={() =>
                document
                  .querySelector<HTMLElement>('aside [role="combobox"]')
                  ?.focus()
              }
              className="sr-only z-50 rounded-full bg-stone-raised px-4 py-2 text-sm font-semibold text-ink shadow-elevation-2 focus-visible:not-sr-only focus-visible:absolute focus-visible:top-3 focus-visible:left-3"
            >
              {t('Map.skipToSearch')}
            </button>
          )}
          <Suspense fallback={null}>
            <RouteUrlSync />
          </Suspense>
          <div className="absolute inset-0">
            {graph.data && (
              <CampusScene
                graph={graph.data}
                buildings={buildings.data ?? []}
                greenery={greenery.data}
                ground={ground.data}
                routeNodeIds={routeData ? frameIds : undefined}
                routeParts={parts.map((part) => part.map((n) => n.id))}
                routeExtent={routeData ? routeExtent : undefined}
                activeNodeId={stepMapId}
                exploreNodeId={exploreNode?.id}
                focusEnu={panoPin}
                sky={sky}
                condition={condition}
                insets={insets}
                frameInsets={frameInsets}
                reducedMotion={reducedMotion}
                assemble={
                  assembling
                    ? { onReveal: reveal, onDone: finishIntro }
                    : undefined
                }
                photoreal={
                  photoreal && PHOTOREAL_TOKEN
                    ? { token: PHOTOREAL_TOKEN, onCredits: setCredits }
                    : undefined
                }
              />
            )}
          </div>

          <AnimatePresence>
            {!dataReady && !graph.isError && (
              <motion.div
                key="splash"
                className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-stone"
                exit={{ opacity: 0 }}
                transition={{ duration: 0.4, ease: EASE }}
              >
                <FanMark className="size-12 animate-fan text-ink" />
                <p className="text-md font-medium text-ink-muted">
                  {t('Map.loading')}
                </p>
              </motion.div>
            )}
          </AnimatePresence>

          <PanelShell
            sheet={!desktop}
            snap={snap}
            heights={heights}
            onSnapChange={setSnap}
            onCoveredHeight={setCovered}
            ready={ready}
            reducedMotion={reducedMotion}
            // Invisible until ready (loading, the opening): out of the tab order.
            inert={panoModal || !ready}
            header={
              <>
                {/* On the sheet every pixel of the peek goes to the search;
                    the name stays for screen readers. */}
                <header
                  className={cn(
                    'flex items-center gap-2.5 px-4 pt-3.5 pb-3',
                    !desktop && 'sr-only',
                  )}
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-[8px] bg-ink text-stone-raised shadow-thumb [--mark-accent:var(--ice-inverse)]">
                    <FanMark className="size-4.5" />
                  </span>
                  <h1 className="truncate text-base font-semibold tracking-heading">
                    {t('Brand.short')}{' '}
                    <span className="ml-0.5 font-normal text-ink-muted">
                      {t('Brand.place')}
                    </span>
                  </h1>
                </header>

                <div
                  role="tablist"
                  aria-label={t('Panel.label')}
                  onKeyDown={onTabKey}
                  className="mx-4 mb-3 grid shrink-0 grid-cols-2 rounded-[10px] bg-fill p-[3px]"
                >
                  {TABS.map((tab) => {
                    const selected = panelTab === tab;
                    return (
                      <button
                        key={tab}
                        type="button"
                        role="tab"
                        id={`tab-${tab}`}
                        aria-selected={selected}
                        aria-controls={`panel-${tab}`}
                        tabIndex={selected ? 0 : -1}
                        onClick={() => selectTab(tab)}
                        className={cn(
                          'relative flex h-7 items-center justify-center rounded-[7px] text-sm font-medium transition-colors duration-150 ease-out-soft',
                          selected
                            ? 'text-ink'
                            : 'text-ink-muted hover:text-ink',
                        )}
                      >
                        {selected && (
                          <motion.span
                            layoutId="panel-tab-thumb"
                            aria-hidden
                            className="absolute inset-0 rounded-[7px] bg-stone-raised shadow-thumb dark:bg-white/14"
                            transition={{ duration: 0.22, ease: EASE }}
                          />
                        )}
                        <span className="relative flex items-center gap-1.5">
                          {tab === 'directions' ? (
                            <Navigation className="size-3.5" aria-hidden />
                          ) : (
                            <MessageCircle className="size-3.5" aria-hidden />
                          )}
                          {t(`Panel.${tab}`)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </>
            }
          >
            <div
              role="tabpanel"
              id="panel-directions"
              aria-labelledby="tab-directions"
              hidden={panelTab !== 'directions'}
              // The bottom padding fades out, so rows scrolling under the
              // panel edge dissolve instead of being cut. The top padding
              // (pulled back up by the margin) leaves the search field's
              // focus ring room inside the scroll box, which clips it.
              className="-mt-1 min-h-0 flex-1 [scrollbar-width:thin] overflow-y-auto overscroll-contain [mask-image:linear-gradient(to_bottom,#000_calc(100%-1rem),transparent)] px-4 pt-1 pb-4"
            >
              {graph.isError ? (
                <p className="rounded-card bg-brick/10 p-3.5 text-sm">
                  {t('Route.apiDown')}
                </p>
              ) : (
                <DirectionsPanel
                  route={routeData}
                  error={route.error ?? undefined}
                  loading={route.isFetching}
                  now={now}
                  reducedMotion={reducedMotion}
                  layout={desktop ? 'panel' : 'sheet'}
                />
              )}
            </div>
            <div
              role="tabpanel"
              id="panel-assistant"
              aria-labelledby="tab-assistant"
              hidden={panelTab !== 'assistant'}
              className="flex min-h-0 flex-1 flex-col px-4 pb-4"
            >
              {assistantMounted && (
                <AssistantPanel
                  onShowDirections={() => selectTab('directions')}
                />
              )}
            </div>
          </PanelShell>

          <motion.div
            inert={panoModal || !ready}
            // Map labels give way to the chrome over the map (OverlayProjector).
            data-map-obstacle
            className="pointer-events-none absolute top-[max(0.5rem,env(safe-area-inset-top))] right-[max(0.5rem,env(safe-area-inset-right))] z-10 flex items-center gap-2 md:top-[max(0.75rem,env(safe-area-inset-top))] md:right-[max(0.75rem,env(safe-area-inset-right))]"
            // Same on server and client: MotionConfig drops the movement
            // for reduced motion, and the fade still lands on opacity 1.
            initial={{ opacity: 0, y: -8 }}
            animate={ready ? { opacity: 1, y: 0 } : undefined}
            transition={{ duration: 0.4, ease: EASE, delay: 0.2 }}
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
            data-map-obstacle
            className="pointer-events-none absolute top-[calc(3.5rem_+_env(safe-area-inset-top))] right-[max(0.5rem,env(safe-area-inset-right))] z-10 md:top-[calc(4.25rem_+_env(safe-area-inset-top))] md:right-[max(0.75rem,env(safe-area-inset-right))]"
            initial={{ opacity: 0, x: 8 }}
            animate={ready ? { opacity: 1, x: 0 } : undefined}
            transition={{ duration: 0.4, ease: EASE, delay: 0.25 }}
          >
            {/* Phones: a compact column under the status pill that steps
                aside when the sheet rises into it. */}
            <div
              inert={panoModal || controlsHidden || !ready}
              className={cn(
                'transition-opacity duration-200 ease-out-soft',
                controlsHidden && 'opacity-0',
              )}
            >
              <MapControls reducedMotion={reducedMotion} />
            </div>
          </motion.div>

          <AnimatePresence>
            {panoNode && (
              <motion.div
                key="pano"
                className={
                  desktop
                    ? 'absolute right-16 bottom-8 z-20 h-[min(30rem,58vh)] w-[min(46rem,calc(100vw-29rem))]'
                    : // Phones: the whole screen, above the sheet.
                      'absolute inset-0 z-30'
                }
                initial={
                  reducedMotion ? false : { opacity: 0, y: 16, scale: 0.98 }
                }
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={
                  reducedMotion
                    ? { opacity: 0 }
                    : { opacity: 0, y: 12, scale: 0.985 }
                }
                transition={{ duration: 0.25, ease: EASE }}
              >
                <PanoInset
                  node={panoNode}
                  next={stepNode ? nextNode : undefined}
                  yaw={panoYaw}
                  title={nodeLabel(panoNode)}
                  step={panoStep}
                  night={sky.phase === 'night' || sky.phase === 'twilight'}
                  reducedMotion={reducedMotion}
                  fullscreen={!desktop}
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

          <Attribution
            hidden={attributionHidden}
            inert={panoModal}
            google={photoreal ? credits : undefined}
          />
          {/* Last in the tab order: the panel and controls come first. */}
          {graph.data && ready && (
            <div inert={panoModal} className="contents">
              <MapOverlays
                nodes={mapNodes}
                buildings={buildings.data ?? []}
                route={drawn}
                doors={doors}
                focusNodeId={panoMapId}
                focusEnu={panoPin}
                destinationNodeId={destinationMapId}
                destinationPlaceId={to?.id}
                destinationEnu={destinationEnu}
                destinationLabel={destinationLabel}
                places={directory.data}
                labelOf={nodeLabel}
                onOpenPano={(node) => setExploreNode(node.id)}
                onPickPlace={pickPlace}
              />
            </div>
          )}
        </div>
      </TooltipProvider>
    </MotionConfig>
  );
}

function useViewport(): { width: number; height: number } {
  const [size, setSize] = useState({ width: 1280, height: 800 });
  useEffect(() => {
    const update = () =>
      setSize({ width: window.innerWidth, height: window.innerHeight });
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return size;
}

/**
 * Sources, always on the map. Desktop: one quiet line in the corner. Mobile:
 * the OpenStreetMap credit riding on top of the sheet, the rest one tap away;
 * it steps aside when the sheet is fully open.
 */
function Attribution({
  hidden,
  inert,
  google,
}: {
  hidden: boolean;
  inert: boolean;
  /** Credits of Google's photorealistic tiles, when they are shown. */
  google?: Credit[];
}) {
  const t = useTranslations();
  const lines = [
    ...(google
      ? [
          [
            ...google.filter((c) => c.text).map((c) => c.text),
            'Cesium ion',
          ].join(' · '),
        ]
      : []),
    t('Attribution.map'),
    t('Attribution.imagery'),
    t('Attribution.weather'),
    t('Brand.independent'),
  ];
  return (
    <>
      <footer
        inert={inert}
        className="map-halo pointer-events-auto absolute right-3 bottom-2 z-10 hidden items-center gap-3.5 text-2xs text-ink-muted md:flex"
      >
        {google && (
          // eslint-disable-next-line @next/next/no-img-element -- Google's own logo asset
          <img
            src="https://maps.gstatic.com/mapfiles/api-3/images/google_gray.svg"
            alt="Google"
            className="h-3 w-auto"
          />
        )}
        {lines.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </footer>
      <footer
        inert={inert || hidden}
        className={cn(
          'map-halo pointer-events-auto absolute bottom-[calc(var(--sheet-h,9.25rem)+0.375rem)] left-3.5 z-10 flex items-center gap-2 text-2xs text-ink-muted transition-opacity duration-200 ease-out-soft md:hidden',
          hidden && 'opacity-0',
        )}
      >
        <span>{t('Attribution.map')}</span>
        <Popover>
          <PopoverTrigger
            className="-m-1.5 flex items-center gap-1 rounded-full p-1.5 font-medium text-ink"
            aria-label={t('Attribution.short')}
          >
            <Info className="size-3" aria-hidden />
            {t('Attribution.short')}
          </PopoverTrigger>
          <PopoverContent
            side="top"
            align="start"
            sideOffset={8}
            className="glass glass-thick w-72 gap-1.5 rounded-card bg-(--glass-bg) p-3.5 text-xs text-ink-muted ring-0"
          >
            {lines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </PopoverContent>
        </Popover>
      </footer>
    </>
  );
}

/** Switching language keeps the route on screen (and in the URL). */
function LanguageSwitch() {
  const t = useTranslations('Language');
  const locale = useLocale();
  const pathname = usePathname();
  const route = useRouteStore(useShallow(routeParamsOf));
  const query = Object.fromEntries(withRouteParams('', route));
  return (
    <Glass
      as="nav"
      radius={999}
      aria-label={t('label')}
      className="pointer-events-auto flex h-9 items-center p-[3px]"
    >
      {(['tr', 'en'] as const).map((l) => (
        <Link
          key={l}
          href={{ pathname, query }}
          locale={l}
          aria-current={l === locale ? 'true' : undefined}
          title={t(l)}
          className={cn(
            'flex h-[30px] min-w-9 items-center justify-center rounded-full px-2 text-xs font-semibold transition-colors duration-150 ease-out-soft',
            l === locale
              ? 'bg-ink text-stone-raised shadow-thumb'
              : 'text-ink-muted hover:text-ink',
          )}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </Glass>
  );
}
