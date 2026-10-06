'use client';

import '@photo-sphere-viewer/core/index.css';

import { Viewer } from '@photo-sphere-viewer/core';
import { CubemapAdapter } from '@photo-sphere-viewer/cubemap-adapter';
import { ChevronLeft, ChevronRight, Maximize2, X } from 'lucide-react';
import { cn } from 'cn';
import { useTranslations } from 'next-intl';
import { type ReactNode, type Ref, useEffect, useRef, useState } from 'react';

import { FanMark } from '@/components/brand/FanMark';
import { Glass } from '@/components/glass/Glass';
import { bearingDeg, yawForBearing } from '@/features/campus/coords';
import type { GraphNode } from '@/features/campus/types';
import { panoFaceUrl } from '@/lib/assets';

export interface PanoStep {
  index: number;
  count: number;
  instruction: string;
  icon: ReactNode;
  distance?: string;
  /** Where the step is when the map cannot say ("Bina içi · −1. kat"). */
  detail?: string;
}

interface Props {
  node: GraphNode;
  /** Where the visitor walks next; the view opens facing it. */
  next?: GraphNode;
  /**
   * Viewer yaw (radians from the front face) to open on instead, where
   * positions cannot tell the way (indoor spots face the tour's hotspots).
   */
  yaw?: number;
  title: string;
  /** Present while following a route; absent when exploring a single spot. */
  step?: PanoStep;
  /** The photos are daylight; at night they get a light blue grade (≤ 25%). */
  night?: boolean;
  reducedMotion: boolean;
  /**
   * Mobile: the view covers the whole screen and acts as a dialog (focus
   * moves to its close button and returns on close).
   */
  fullscreen?: boolean;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  onStep?: (index: number) => void;
}

function faces(scene: string) {
  return {
    left: panoFaceUrl(scene, 'l'),
    front: panoFaceUrl(scene, 'f'),
    right: panoFaceUrl(scene, 'r'),
    back: panoFaceUrl(scene, 'b'),
    top: panoFaceUrl(scene, 'u'),
    bottom: panoFaceUrl(scene, 'd'),
  };
}

function yawTowards(node: GraphNode, next?: GraphNode): number {
  if (!next) return 0;
  const bearing = bearingDeg(
    [node.enu[0], node.enu[1]],
    [next.enu[0], next.enu[1]],
  );
  return yawForBearing(bearing, node.heading_deg);
}

export function PanoInset({
  node,
  next,
  yaw,
  title,
  step,
  night = false,
  reducedMotion,
  fullscreen = false,
  onClose,
  onPrevious,
  onNext,
  onStep,
}: Props) {
  const t = useTranslations('Pano');
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | undefined>(undefined);
  /** Scene currently shown, so the first render doesn't reload (and abort) it. */
  const shown = useRef<string | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Full screen, the rest of the page is inert: move focus in, and give it
  // back to whatever opened the view (a route step, a map spot) on close.
  useEffect(() => {
    if (!fullscreen) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : undefined;
    closeButton.current?.focus({ preventScroll: true });
    return () => {
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [fullscreen]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let instance: Viewer | undefined;
    // Create on the next frame: StrictMode mounts, unmounts and remounts
    // synchronously, and three's FileLoader shares in-flight requests per URL,
    // so destroying the first viewer would abort the second one's faces too
    // (PSV swallows AbortError and keeps its loader up forever).
    const frame = requestAnimationFrame(() => {
      instance = new Viewer({
        container: element,
        adapter: CubemapAdapter,
        panorama: faces(node.id),
        defaultYaw: yaw ?? yawTowards(node, next),
        defaultPitch: -0.05,
        defaultZoomLvl: 30,
        navbar: false,
        loadingTxt: '',
        mousewheelCtrlKey: true,
      });
      instance.addEventListener('panorama-loaded', () => setLoading(false));
      viewer.current = instance;
      shown.current = node.id;
    });
    return () => {
      cancelAnimationFrame(frame);
      instance?.destroy();
      viewer.current = undefined;
      shown.current = undefined;
    };
    // The viewer is created once; later steps swap panoramas below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const instance = viewer.current;
    if (!instance) return;
    const position = { yaw: yaw ?? yawTowards(node, next), pitch: -0.05 };
    if (shown.current === node.id) {
      // Same panorama (e.g. first render): just face the next step.
      if (reducedMotion) instance.rotate(position);
      else void instance.animate({ ...position, speed: '4rpm' });
      return;
    }
    shown.current = node.id;
    void instance.setPanorama(faces(node.id), {
      // Crossfade without spinning the camera: the new view already faces the route.
      transition: reducedMotion
        ? false
        : { speed: 250, rotation: false, effect: 'fade' },
      position,
      showLoader: false,
    });
  }, [node, next, yaw, reducedMotion]);

  return (
    <section
      aria-label={t('title')}
      role={fullscreen ? 'dialog' : undefined}
      aria-modal={fullscreen ? true : undefined}
      className={cn(
        'pointer-events-auto relative isolate h-full overflow-hidden bg-[#0e141e] [&_.psv-loader-container]:hidden',
        fullscreen
          ? 'rounded-none'
          : 'rounded-[22px] shadow-elevation-2 ring-1 ring-black/10',
      )}
    >
      <div ref={container} className="absolute inset-0" />
      <div
        aria-hidden
        className={[
          'pointer-events-none absolute inset-0 bg-[#0b1838] mix-blend-multiply transition-opacity duration-800 ease-out-soft',
          night ? 'opacity-25' : 'opacity-0',
        ].join(' ')}
      />

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[radial-gradient(circle_at_50%_40%,#2a3445,#0e141e)]">
          <FanMark className="size-12 animate-fan text-white/90" />
        </div>
      )}

      {/* Scrims keep the glass controls legible over bright skies and paving. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-linear-to-b from-black/40 to-transparent"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-linear-to-t from-black/30 to-transparent"
      />

      <header
        className={cn(
          'pointer-events-none absolute inset-x-2.5 flex items-start gap-2',
          fullscreen
            ? 'top-[max(0.625rem,env(safe-area-inset-top))]'
            : 'top-2.5',
        )}
      >
        <Glass
          variant="tint"
          radius={16}
          className="pointer-events-auto flex min-w-0 items-center gap-2.5 py-1.5 pr-3.5 pl-1.5"
        >
          {step ? (
            <span className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-route text-on-route">
              {step.icon}
            </span>
          ) : (
            <span className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-white/15">
              <FanMark className="size-4.5 text-white" />
            </span>
          )}
          <span className="min-w-0">
            <span className="block truncate text-md leading-tight font-semibold tracking-heading">
              {step ? step.instruction : title}
            </span>
            <span className="tabular block truncate text-xs text-white/75">
              {step
                ? `${t('stepOf', { index: step.index + 1, count: step.count })}${step.distance ? `, ${step.distance}` : ''}${step.detail ? ` · ${step.detail}` : ''}`
                : t('explore')}
            </span>
          </span>
        </Glass>
        <span className="flex-1" />
        <Glass
          variant="tint"
          radius={999}
          className="pointer-events-auto flex p-0.5"
        >
          {/* Already full screen on phones, where the Fullscreen API is patchy. */}
          {!fullscreen && (
            <GlassIconButton
              label={t('expand')}
              onClick={() => viewer.current?.enterFullscreen()}
            >
              <Maximize2 className="size-4" />
            </GlassIconButton>
          )}
          <GlassIconButton
            label={t('close')}
            onClick={onClose}
            buttonRef={closeButton}
          >
            <X className="size-4.5" />
          </GlassIconButton>
        </Glass>
      </header>

      {step && (
        <footer
          className={cn(
            'pointer-events-none absolute inset-x-0 flex justify-center',
            // Full screen: clear of the home indicator and the thumb zone edge.
            fullscreen
              ? 'bottom-[max(1.25rem,env(safe-area-inset-bottom))]'
              : 'bottom-2.5',
          )}
        >
          <Glass
            variant="tint"
            radius={999}
            className="pointer-events-auto flex items-center gap-0.5 p-0.5"
          >
            <GlassIconButton
              label={t('previous')}
              onClick={onPrevious}
              disabled={!onPrevious}
            >
              <ChevronLeft className="size-5" />
            </GlassIconButton>
            <span className="flex items-center gap-1.5 px-2">
              {Array.from({ length: step.count }, (_, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onStep?.(i)}
                  aria-label={t('goToStep', { index: i + 1 })}
                  aria-current={i === step.index ? 'step' : undefined}
                  className={[
                    // A 6 px dot with a finger-sized hit area around it.
                    'relative h-1.5 rounded-full transition-all duration-250 ease-out-soft after:absolute after:-inset-x-0.5 after:-inset-y-3',
                    i === step.index
                      ? 'w-5 bg-white'
                      : 'w-1.5 bg-white/45 hover:bg-white/70',
                  ].join(' ')}
                />
              ))}
            </span>
            <GlassIconButton
              label={t('next')}
              onClick={onNext}
              disabled={!onNext}
            >
              <ChevronRight className="size-5" />
            </GlassIconButton>
          </Glass>
        </footer>
      )}
    </section>
  );
}

function GlassIconButton({
  label,
  onClick,
  disabled,
  buttonRef,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  buttonRef?: Ref<HTMLButtonElement>;
  children: ReactNode;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="flex size-9 items-center justify-center rounded-full text-white transition-colors duration-150 ease-out-soft hover:bg-white/15 disabled:opacity-35 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}
