'use client';

import { useTranslations } from 'next-intl';
import { type ReactNode, useLayoutEffect, useMemo, useRef } from 'react';
import { Vector3 } from 'three';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { anchors } from '@/features/campus/anchors';
import { enuToWorld } from '@/features/campus/coords';
import { openRing } from '@/features/campus/geometry';
import type { Building, GraphNode } from '@/features/campus/types';

import { useCameraStore, type ZoomTier } from './cameraStore';

/** A DOM element that the scene's projector keeps over a 3D point. */
function MapAnchor({
  id,
  position,
  children,
}: {
  id: string;
  position: [number, number, number];
  children: ReactNode;
}) {
  const element = useRef<HTMLDivElement>(null);
  const [x, y, z] = position;
  useLayoutEffect(() => {
    if (!element.current) return;
    anchors.set(id, {
      element: element.current,
      position: new Vector3(x, y, z),
    });
    return () => {
      anchors.delete(id);
    };
  }, [id, x, y, z]);
  return (
    <div
      ref={element}
      className="absolute top-0 left-0 will-change-transform"
      // Off-screen until the projector places it on the next frame.
      style={{ transform: 'translate3d(-200px, -200px, 0)' }}
    >
      {children}
    </div>
  );
}

const atNode = (node: GraphNode, up = 0.6) =>
  enuToWorld(node.enu[0], node.enu[1], up);

function StartPin({ node }: { node: GraphNode }) {
  return (
    <MapAnchor id="pin-start" position={atNode(node)}>
      <span
        aria-hidden
        className="block size-5 -translate-1/2 rounded-full border-[5px] border-route bg-white shadow-[0_2px_8px_rgb(19_26_36/0.35)]"
      />
    </MapAnchor>
  );
}

function DestinationPin({ node, label }: { node: GraphNode; label: string }) {
  return (
    <MapAnchor id="pin-end" position={atNode(node)}>
      {/* The pin's tip sits on the node: shift up by its height, left by half its width. */}
      <div
        aria-hidden
        className="flex -translate-x-[15px] -translate-y-full items-end gap-1.5"
      >
        <svg
          viewBox="0 0 30 40"
          className="h-10 w-[30px] drop-shadow-[0_4px_6px_rgb(19_26_36/0.35)]"
        >
          <path
            d="M15 0C6.7 0 0 6.6 0 14.8 0 25.7 15 40 15 40s15-14.3 15-25.2C30 6.6 23.3 0 15 0Z"
            fill="var(--brick)"
          />
          <circle cx="15" cy="14.5" r="5.5" fill="#fff" />
        </svg>
        <span className="mb-5 rounded-full bg-stone-raised/92 px-2.5 py-1 font-display text-sm font-semibold whitespace-nowrap text-ink shadow-elevation-1">
          {label}
        </span>
      </div>
    </MapAnchor>
  );
}

function FocusPulse({ node }: { node: GraphNode }) {
  return (
    <MapAnchor id="pin-focus" position={atNode(node)}>
      <span
        aria-hidden
        className="relative flex size-6 -translate-1/2 items-center justify-center"
      >
        <span className="absolute inset-0 animate-ping-soft rounded-full bg-route" />
        <span className="relative size-4 rounded-full border-[3px] border-white bg-route shadow-[0_2px_6px_rgb(19_26_36/0.4)]" />
      </span>
    </MapAnchor>
  );
}

/** Spots with a 360° panorama; clicking one opens it. */
function PanoSpots({
  nodes,
  tier,
  hidden,
  quiet,
  labelOf,
  onOpen,
}: {
  nodes: GraphNode[];
  tier: ZoomTier;
  hidden: Set<string>;
  /** While a route is shown, spots only appear up close. */
  quiet: boolean;
  labelOf: (node: GraphNode) => string;
  onOpen: (node: GraphNode) => void;
}) {
  const t = useTranslations('Map');
  return (
    <>
      {nodes.map((node) => {
        const visible =
          !hidden.has(node.id) &&
          (tier === 'near' || (tier === 'mid' && !quiet));
        if (!visible) return null;
        const label = labelOf(node);
        return (
          <MapAnchor
            key={node.id}
            id={`spot-${node.id}`}
            position={atNode(node, 0.4)}
          >
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    onClick={() => onOpen(node)}
                    aria-label={t('panoSpot', { label })}
                    className={[
                      'pointer-events-auto block -translate-1/2 rounded-full border-route bg-white shadow-[0_1px_3px_rgb(19_26_36/0.35)]',
                      'transition-transform duration-150 ease-out-soft hover:scale-150 focus-visible:scale-150',
                      tier === 'near'
                        ? 'size-3.5 border-[3px]'
                        : 'size-2.5 border-2',
                    ].join(' ')}
                  />
                }
              />
              <TooltipContent side="top" sideOffset={8}>
                {t('panoSpot', { label })}
              </TooltipContent>
            </Tooltip>
          </MapAnchor>
        );
      })}
    </>
  );
}

/** "İstanbul Aydın Üniversitesi A Binası" -> "A". */
export function buildingCode(name: string | null): string | undefined {
  const match = name?.match(
    /(?:^|\s)([A-ZÇĞİÖŞÜ](?:-[A-ZÇĞİÖŞÜ])?)\s+(?:Binası|Blok)/u,
  );
  return match?.[1];
}

function BuildingLabels({
  buildings,
  tier,
}: {
  buildings: Building[];
  tier: ZoomTier;
}) {
  const t = useTranslations('Map');
  const labels = useMemo(() => {
    const out: {
      id: string;
      code: string;
      position: [number, number, number];
    }[] = [];
    for (const b of buildings) {
      const code = b.campus ? buildingCode(b.name) : undefined;
      if (!code) continue;
      const ring = openRing(b.outline);
      const [e, n] = ring.reduce(
        ([se, sn], [pe, pn]) => [se + pe, sn + pn],
        [0, 0],
      );
      out.push({
        id: b.id,
        code,
        position: enuToWorld(e / ring.length, n / ring.length, b.height_m + 2),
      });
    }
    return out;
  }, [buildings]);

  return (
    <>
      {labels.map((label) => (
        <MapAnchor
          key={label.id}
          id={`label-${label.id}`}
          position={label.position}
        >
          <span
            aria-hidden
            className={[
              'flex -translate-1/2 items-center gap-1.5 rounded-full bg-stone-raised/92 py-0.5 pr-2.5 pl-0.5 whitespace-nowrap shadow-elevation-1 transition-opacity duration-250',
              tier === 'far' ? 'opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <span className="flex size-6 items-center justify-center rounded-full bg-ochre font-display text-sm font-bold text-[#131a24]">
              {label.code}
            </span>
            <span className="font-display text-sm font-semibold text-ink">
              {t('block', { code: label.code })}
            </span>
          </span>
        </MapAnchor>
      ))}
    </>
  );
}

interface OverlayProps {
  nodes: GraphNode[];
  buildings: Building[];
  route: GraphNode[];
  /** Node shown in 360° (a route step or an explored spot). */
  focusNodeId?: string;
  destinationLabel?: string;
  labelOf: (node: GraphNode) => string;
  onOpenPano: (node: GraphNode) => void;
}

/** Everything drawn over the 3D map: labels, route pins and 360° spots. */
export function MapOverlays({
  nodes,
  buildings,
  route,
  focusNodeId,
  destinationLabel,
  labelOf,
  onOpenPano,
}: OverlayProps) {
  const tier = useCameraStore((s) => s.tier);
  const hasRoute = route.length > 1;
  const start = hasRoute ? route[0] : undefined;
  const end = hasRoute ? route[route.length - 1] : undefined;
  const focus = focusNodeId
    ? nodes.find((n) => n.id === focusNodeId)
    : undefined;
  const hidden = useMemo(
    () =>
      new Set([
        ...(hasRoute ? route.map((n) => n.id) : []),
        ...(focusNodeId ? [focusNodeId] : []),
      ]),
    [hasRoute, route, focusNodeId],
  );

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <BuildingLabels buildings={buildings} tier={tier} />
      <PanoSpots
        nodes={nodes}
        tier={tier}
        hidden={hidden}
        quiet={hasRoute}
        labelOf={labelOf}
        onOpen={onOpenPano}
      />
      {start && start.id !== focus?.id && <StartPin node={start} />}
      {end && (
        <DestinationPin node={end} label={destinationLabel ?? labelOf(end)} />
      )}
      {focus && <FocusPulse node={focus} />}
    </div>
  );
}
