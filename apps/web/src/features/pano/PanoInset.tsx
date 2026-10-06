'use client';

import '@photo-sphere-viewer/core/index.css';

import { Viewer } from '@photo-sphere-viewer/core';
import { CubemapAdapter } from '@photo-sphere-viewer/cubemap-adapter';
import { ChevronLeft, ChevronRight, Maximize2, X } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { type ReactNode, useEffect, useRef, useState } from 'react';

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
}

interface Props {
  node: GraphNode;
  /** Where the visitor walks next; the view opens facing it. */
  next?: GraphNode;
  title: string;
  /** Present while following a route; absent when exploring a single spot. */
  step?: PanoStep;
  /** The photos are daylight; at night they get a light blue grade (≤ 25%). */
  night?: boolean;
  reducedMotion: boolean;
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
  title,
  step,
  night = false,
  reducedMotion,
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
        defaultYaw: yawTowards(node, next),
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
    const position = { yaw: yawTowards(node, next), pitch: -0.05 };
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
  }, [node, next, reducedMotion]);

  return (
    <section
      aria-label={t('title')}
      className="pointer-events-auto relative isolate h-full overflow-hidden rounded-[26px] bg-ink shadow-elevation-2 [&_.psv-loader-container]:hidden"
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
          <FanMark className="size-14 animate-fan text-white" />
        </div>
      )}

      {/* Scrims keep the glass controls legible over bright skies and paving. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-linear-to-b from-black/35 to-transparent"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-linear-to-t from-black/30 to-transparent"
      />

      <header className="pointer-events-none absolute inset-x-3 top-3 flex items-start gap-2">
        <Glass
          variant="tint"
          radius={18}
          className="pointer-events-auto flex min-w-0 items-center gap-3 py-2 pr-4 pl-2"
        >
          {step ? (
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-route text-white">
              {step.icon}
            </span>
          ) : (
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/15">
              <FanMark className="size-5 text-white" />
            </span>
          )}
          <span className="min-w-0">
            <span className="block truncate font-display text-md leading-tight font-semibold">
              {step ? step.instruction : title}
            </span>
            <span className="block truncate text-xs text-white/75">
              {step
                ? `${t('stepOf', { index: step.index + 1, count: step.count })}${step.distance ? `, ${step.distance}` : ''}`
                : t('explore')}
            </span>
          </span>
        </Glass>
        <span className="flex-1" />
        <Glass variant="tint" radius={999} className="pointer-events-auto flex">
          <GlassIconButton
            label={t('expand')}
            onClick={() => viewer.current?.enterFullscreen()}
          >
            <Maximize2 className="size-4" />
          </GlassIconButton>
          <GlassIconButton label={t('close')} onClick={onClose}>
            <X className="size-4.5" />
          </GlassIconButton>
        </Glass>
      </header>

      {step && (
        <footer className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
          <Glass
            variant="tint"
            radius={999}
            className="pointer-events-auto flex items-center gap-1 p-1"
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
                    'h-1.5 rounded-full transition-all duration-250 ease-out-soft',
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
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="flex size-10 items-center justify-center rounded-full text-white transition-colors duration-150 ease-out-soft hover:bg-white/15 disabled:opacity-35 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}
