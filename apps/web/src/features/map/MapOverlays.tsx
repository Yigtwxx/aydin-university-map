'use client';

import { DoorOpen } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useMemo } from 'react';

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { FanMark } from '@/components/brand/FanMark';
import { enuToWorld } from '@/features/campus/coords';
import { openRing } from '@/features/campus/geometry';
import { type Place, useTerrain } from '@/features/campus/queries';
import { groundUnder, type Terrain } from '@/features/campus/terrain';
import type { Building, GraphNode } from '@/features/campus/types';

import { blockChips } from './blockChips';
import { useCameraStore, type ZoomTier } from './cameraStore';
import { MapAnchor } from './MapAnchor';
import { PoiLayer } from './PoiLayer';

/** Outdoor spots further than this from any entrance keep their bare name. */
const NEAR_DOOR_M = 90;

/** A point `up` metres above the ground there (terraces, stairs). */
const atEnu = (
  terrain: Terrain,
  [east, north]: readonly [number, number],
  up = 0.6,
) => enuToWorld(east, north, terrain.heightAt(east, north) + up);

const atNode = (terrain: Terrain, node: GraphNode, up = 0.6) =>
  atEnu(terrain, [node.enu[0], node.enu[1]], up);

/**
 * A door where the drawn route stops to go inside (or through a building)
 * and where it comes out again: the gap between them is not a line outside.
 */
function DoorPin({ node, terrain }: { node: GraphNode; terrain: Terrain }) {
  return (
    <MapAnchor
      id={`pin-door-${node.id}`}
      position={atNode(terrain, node)}
      layer={3}
    >
      <span
        aria-hidden
        data-marker
        className="flex size-5 -translate-1/2 items-center justify-center rounded-full bg-white text-route shadow-[0_0_0_2.5px_var(--route),0_2px_6px_rgb(15_23_36/0.35)]"
      >
        <DoorOpen className="size-3" strokeWidth={2.5} />
      </span>
    </MapAnchor>
  );
}

function StartPin({ node, terrain }: { node: GraphNode; terrain: Terrain }) {
  return (
    <MapAnchor id="pin-start" position={atNode(terrain, node)} layer={3}>
      <span
        aria-hidden
        data-marker
        className="block size-4.5 -translate-1/2 rounded-full border-[4.5px] border-route bg-white shadow-[0_0_0_1.5px_#fff,0_2px_8px_rgb(15_23_36/0.35)]"
      />
    </MapAnchor>
  );
}

function DestinationPin({
  position,
  label,
}: {
  position: [number, number, number];
  label: string;
}) {
  return (
    <MapAnchor id="pin-end" position={position} layer={4}>
      {/* The pin's tip sits on the node: shift up by its height, left by half its width. */}
      <div
        aria-hidden
        className="flex -translate-x-[13px] -translate-y-full items-end gap-1.5"
      >
        <svg
          data-marker
          viewBox="0 0 26 34"
          className="h-[34px] w-[26px] drop-shadow-[0_3px_5px_rgb(15_23_36/0.35)]"
        >
          <path
            d="M13 .75C6.2.75.75 6.1.75 12.8c0 9.1 12.25 20.45 12.25 20.45S25.25 21.9 25.25 12.8C25.25 6.1 19.8.75 13 .75Z"
            fill="var(--brick)"
            stroke="#fff"
            strokeWidth="1.5"
          />
          <circle cx="13" cy="12.6" r="4.4" fill="#fff" />
        </svg>
        <span
          data-label
          className="mb-[18px] rounded-full bg-stone-raised/92 px-2.5 py-1 text-sm font-semibold tracking-heading whitespace-nowrap text-ink shadow-elevation-1 ring-1 ring-hairline backdrop-blur-md"
        >
          {label}
        </span>
      </div>
    </MapAnchor>
  );
}

function FocusPulse({ position }: { position: [number, number, number] }) {
  return (
    <MapAnchor id="pin-focus" position={position} layer={4}>
      <span
        aria-hidden
        className="relative flex size-6 -translate-1/2 items-center justify-center"
      >
        <span className="absolute inset-0 animate-ping-soft rounded-full bg-route" />
        <span className="relative size-4 rounded-full border-[3px] border-white bg-route shadow-[0_2px_6px_rgb(15_23_36/0.4)]" />
      </span>
    </MapAnchor>
  );
}

/**
 * Spots with a 360° panorama; clicking one opens it. Fewer, more meaningful
 * markers: entrances (the places people walk to) show at every zoom level,
 * ochre-rimmed and named; plain path spots only appear up close, small and
 * quiet.
 */
function PanoSpots({
  nodes,
  terrain,
  tier,
  hidden,
  quiet,
  labelOf,
  onOpen,
}: {
  nodes: GraphNode[];
  terrain: Terrain;
  tier: ZoomTier;
  hidden: Set<string>;
  /** While a route is shown: entrance names and path spots give way to it. */
  quiet: boolean;
  labelOf: (node: GraphNode) => string;
  onOpen: (node: GraphNode) => void;
}) {
  const t = useTranslations('Map');
  const near = tier === 'near';
  // A place can have several entrance spots under one name; label only the
  // first, so names never stack up on each other.
  const namedIds = useMemo(() => {
    const seen = new Set<string>();
    const ids = new Set<string>();
    for (const node of nodes) {
      if (node.kind !== 'entrance') continue;
      const label = labelOf(node);
      if (seen.has(label)) continue;
      seen.add(label);
      ids.add(node.id);
    }
    return ids;
  }, [nodes, labelOf]);
  // Many outdoor spots share one tour name ("Kampüs"): name them after the
  // nearest entrance too, so a screen reader can tell them apart.
  const nearName = useMemo(() => {
    const doors = nodes.filter((n) => n.kind === 'entrance');
    const names = new Map<string, string>();
    for (const node of nodes) {
      if (node.kind === 'entrance') continue;
      let best: GraphNode | undefined;
      let bestD = NEAR_DOOR_M;
      for (const door of doors) {
        const d = Math.hypot(
          door.enu[0] - node.enu[0],
          door.enu[1] - node.enu[1],
        );
        if (d < bestD) {
          bestD = d;
          best = door;
        }
      }
      if (best) names.set(node.id, labelOf(best));
    }
    return names;
  }, [nodes, labelOf]);
  return (
    <>
      {nodes.map((node) => {
        const entrance = node.kind === 'entrance';
        // Plain path spots only up close, and not around a route, where they
        // would crowd its line.
        if (hidden.has(node.id) || (!entrance && (!near || quiet))) return null;
        const label = labelOf(node);
        const door = nearName.get(node.id);
        const name = door
          ? t('panoSpotNear', { label, near: door })
          : t('panoSpot', { label });
        // Names only up close: on the overview they would collide.
        // Overlapping names are hidden by the projector (declutter).
        const named =
          (near || tier === 'mid') && !quiet && namedIds.has(node.id);
        return (
          <MapAnchor
            key={node.id}
            id={`spot-${node.id}`}
            position={atNode(terrain, node, 0.4)}
            layer={entrance ? 2 : 1}
          >
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    onClick={() => onOpen(node)}
                    aria-label={name}
                    // A 24 px hit target around a small dot.
                    className="group pointer-events-auto flex size-6 -translate-1/2 items-center justify-center rounded-full"
                  />
                }
              >
                <span
                  aria-hidden
                  data-marker
                  className={[
                    'block rounded-full bg-white transition-transform duration-150 ease-out-soft group-hover:scale-140 group-focus-visible:scale-140',
                    !entrance
                      ? 'size-2 shadow-[0_0_0_1px_rgb(15_23_36/0.22),0_1px_3px_rgb(15_23_36/0.3)]'
                      : near
                        ? 'size-3 shadow-[0_0_0_2.5px_var(--ochre),0_1px_4px_rgb(15_23_36/0.45)]'
                        : tier === 'mid'
                          ? 'size-2.5 shadow-[0_0_0_2px_var(--ochre),0_1px_3px_rgb(15_23_36/0.4)]'
                          : 'size-2 shadow-[0_0_0_1.5px_var(--ochre),0_1px_2px_rgb(15_23_36/0.4)]',
                  ].join(' ')}
                />
                {named && (
                  <span
                    aria-hidden
                    data-label
                    className="map-halo pointer-events-none absolute top-1/2 left-full ml-0.5 -translate-y-1/2 text-xs font-semibold tracking-heading whitespace-nowrap text-ink transition-opacity duration-150"
                  >
                    {label}
                  </span>
                )}
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={6}>
                {name}
              </TooltipContent>
            </Tooltip>
          </MapAnchor>
        );
      })}
    </>
  );
}

function BuildingLabels({
  buildings,
  nodes,
  tier,
}: {
  buildings: Building[];
  nodes: GraphNode[];
  tier: ZoomTier;
}) {
  const t = useTranslations('Map');
  const terrain = useTerrain();
  const labels = useMemo(
    () => blockChips(buildings, nodes, (b) => groundUnder(terrain, b.outline)),
    [buildings, nodes, terrain],
  );

  const near = tier === 'near';
  return (
    <>
      {labels.map((label) => (
        <MapAnchor
          key={label.id}
          id={`label-${label.id}`}
          position={label.position}
          layer={2}
        >
          <span
            aria-hidden
            data-yield
            className={[
              'flex -translate-1/2 items-center gap-1.5 whitespace-nowrap transition-opacity duration-250 ease-out-soft',
              tier === 'far' ? 'opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <span
              data-marker
              className="flex h-5.5 min-w-5.5 items-center justify-center rounded-[7px] bg-ochre px-1 text-xs font-semibold text-ochre-ink shadow-[0_0_0_1.5px_#fff,0_2px_6px_rgb(15_23_36/0.3)]"
            >
              {label.code}
            </span>
            {near && (
              <span
                data-label
                className="map-halo text-sm font-semibold tracking-heading text-ink transition-opacity duration-150"
              >
                {t('block', { code: label.code })}
              </span>
            )}
          </span>
        </MapAnchor>
      ))}
    </>
  );
}

/** One name for the whole campus when zoomed out, where block labels hide. */
function CampusLabel({
  buildings,
  tier,
}: {
  buildings: Building[];
  tier: ZoomTier;
}) {
  const t = useTranslations('Map');
  const centre = useMemo(() => {
    const campus = buildings.filter((b) => b.campus);
    if (campus.length === 0) return undefined;
    let e = 0;
    let n = 0;
    let count = 0;
    for (const b of campus)
      for (const [pe, pn] of openRing(b.outline)) {
        e += pe;
        n += pn;
        count++;
      }
    return enuToWorld(e / count, n / count, 40);
  }, [buildings]);
  if (!centre || tier !== 'far') return null;
  return (
    <MapAnchor id="label-campus" position={centre} layer={3}>
      <span
        data-label
        className="flex -translate-1/2 items-center gap-1.5 rounded-full bg-stone-raised/90 py-1 pr-3 pl-1 text-sm font-semibold tracking-heading whitespace-nowrap text-ink shadow-elevation-1 ring-1 ring-hairline backdrop-blur-md"
      >
        <span className="flex size-6 items-center justify-center rounded-full bg-ink text-stone-raised">
          <FanMark className="size-3.5" />
        </span>
        {t('campus')}
      </span>
    </MapAnchor>
  );
}

interface OverlayProps {
  nodes: GraphNode[];
  buildings: Building[];
  route: GraphNode[];
  /** Doors at the ends of the route's gaps (indoors, passages). */
  doors?: GraphNode[];
  /** Node shown in 360° (a route step or an explored spot). */
  focusNodeId?: string;
  /**
   * Where the 360° spot really is when its node only borrows a position (a
   * business's own indoor panorama, at its storefront), ENU metres.
   */
  focusEnu?: readonly [number, number];
  /** The chosen destination; pinned even before a route exists. */
  destinationNodeId?: string;
  /** Its place id; a business there drops its own pin for the destination's. */
  destinationPlaceId?: string;
  /**
   * The destination's storefront (a business with a measured pin), ENU
   * metres: the pin stands there instead of on the node.
   */
  destinationEnu?: readonly [number, number];
  destinationLabel?: string;
  /** The place directory: its businesses and services get pins. */
  places?: readonly Place[];
  labelOf: (node: GraphNode) => string;
  onOpenPano: (node: GraphNode) => void;
  /** A business pin was picked: make it the destination. */
  onPickPlace: (place: Place) => void;
}

const NO_PLACES: readonly Place[] = [];

/**
 * Everything drawn over the 3D map: labels, route pins, business pins and
 * 360° spots.
 */
export function MapOverlays({
  nodes,
  buildings,
  route,
  doors = [],
  focusNodeId,
  focusEnu,
  destinationNodeId,
  destinationPlaceId,
  destinationEnu,
  destinationLabel,
  places = NO_PLACES,
  labelOf,
  onOpenPano,
  onPickPlace,
}: OverlayProps) {
  const tier = useCameraStore((s) => s.tier);
  const terrain = useTerrain();
  const hasRoute = route.length > 1;
  const start = hasRoute ? route[0] : undefined;
  const end = hasRoute
    ? route[route.length - 1]
    : destinationNodeId
      ? nodes.find((n) => n.id === destinationNodeId)
      : undefined;
  const focus = focusNodeId
    ? nodes.find((n) => n.id === focusNodeId)
    : undefined;
  const hidden = useMemo(
    () =>
      new Set([
        ...(hasRoute ? route.map((n) => n.id) : []),
        ...(focusNodeId ? [focusNodeId] : []),
        ...(destinationNodeId ? [destinationNodeId] : []),
      ]),
    [hasRoute, route, focusNodeId, destinationNodeId],
  );

  const quiet = hasRoute || Boolean(destinationNodeId);
  // A business's storefront, else the node (a business of its own, `poi:`
  // id, has no node before its route arrives).
  const destination = destinationEnu
    ? atEnu(terrain, destinationEnu)
    : end
      ? atNode(terrain, end)
      : undefined;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <CampusLabel buildings={buildings} tier={tier} />
      <BuildingLabels buildings={buildings} nodes={nodes} tier={tier} />
      <PanoSpots
        nodes={nodes}
        terrain={terrain}
        tier={tier}
        hidden={hidden}
        quiet={quiet}
        labelOf={labelOf}
        onOpen={onOpenPano}
      />
      <PoiLayer
        places={places}
        tier={tier}
        quiet={quiet}
        hiddenId={destinationPlaceId}
        onPick={onPickPlace}
      />
      {doors
        .filter((n) => n.id !== focus?.id)
        .map((n) => (
          <DoorPin key={n.id} node={n} terrain={terrain} />
        ))}
      {start && start.id !== focus?.id && (
        <StartPin node={start} terrain={terrain} />
      )}
      {destination && (
        <DestinationPin
          position={destination}
          label={destinationLabel ?? (end ? labelOf(end) : '')}
        />
      )}
      {focus && (
        <FocusPulse
          position={
            focusEnu ? atEnu(terrain, focusEnu) : atNode(terrain, focus)
          }
        />
      )}
    </div>
  );
}
