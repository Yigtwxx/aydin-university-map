import { enuToWorld } from '@/features/campus/coords';
import { openRing } from '@/features/campus/geometry';
import type { Building, GraphNode } from '@/features/campus/types';

/** "İstanbul Aydın Üniversitesi A Binası" -> "A". */
export function buildingCode(name: string | null): string | undefined {
  const match = name?.match(
    /(?:^|\s)([A-ZÇĞİÖŞÜ](?:-[A-ZÇĞİÖŞÜ])?)\s+(?:Binası|Blok)/u,
  );
  return match?.[1];
}

export interface BlockChip {
  /** Stable key: the block code, or the building id for OSM-only chips. */
  id: string;
  code: string;
  position: [number, number, number];
}

/** An entrance this close to a footprint belongs to that building. */
const DOOR_TO_WALL_M = 14;
/** The chip sits this far inside the building from its door. */
const INSET_M = 10;
/** Height of a chip standing at a door with no footprint around it. */
const DOOR_CHIP_M = 8;

type Ring = [number, number][];

function centroidOf(ring: Ring): [number, number] {
  let e = 0;
  let n = 0;
  for (const [x, y] of ring) {
    e += x;
    n += y;
  }
  return [e / ring.length, n / ring.length];
}

function inside(p: [number, number], ring: Ring): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if (
      yi > p[1] !== yj > p[1] &&
      p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi
    )
      hit = !hit;
  }
  return hit;
}

/** Metres from `p` to the footprint (0 inside). */
export function distanceToRing(p: [number, number], ring: Ring): number {
  if (inside(p, ring)) return 0;
  let best = Infinity;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const b = ring[(i + 1) % ring.length]!;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy || 1;
    const t = Math.max(
      0,
      Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2),
    );
    best = Math.min(
      best,
      Math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dy * t)),
    );
  }
  return best;
}

/**
 * Block letters on the map, from the tour itself: each block's chip stands
 * over the wing its entrance opens into, so the chip and the route's "enter
 * M Blok" agree (OSM names one footprint "B Binası" where the tour has the
 * B, G-H and M entrances). A door that stands at another building while a
 * footprint carries its own letter (a mis-posed panorama) yields to that
 * footprint. Campus buildings whose OSM letter no tour block uses keep that
 * letter.
 */
export function blockChips(
  buildings: Building[],
  nodes: GraphNode[],
): BlockChip[] {
  const shapes = buildings.map((b) => ({ b, ring: openRing(b.outline) }));
  const named = new Map<string, (typeof shapes)[number]>();
  for (const s of shapes) {
    const code = s.b.campus ? buildingCode(s.b.name) : undefined;
    if (code && s.ring.length >= 3 && !named.has(code)) named.set(code, s);
  }
  const doors = new Map<
    string,
    { node: GraphNode; d: number; shape?: (typeof shapes)[number] }
  >();
  for (const node of nodes) {
    // Measured doors only: spots without their own position borrow one.
    if (node.kind !== 'entrance' || !node.building || node.anchor) continue;
    const p: [number, number] = [node.enu[0], node.enu[1]];
    let d = Infinity;
    let shape: (typeof shapes)[number] | undefined;
    for (const s of shapes) {
      if (s.ring.length < 3) continue;
      const di = distanceToRing(p, s.ring);
      if (di < d) {
        d = di;
        shape = s;
      }
    }
    const known = doors.get(node.building);
    if (!known || d < known.d) doors.set(node.building, { node, d, shape });
  }

  const chips: BlockChip[] = [];
  for (const [code, { node, d, shape }] of doors) {
    const [e, n] = node.enu;
    const own = named.get(code);
    if (own && (shape !== own || d > DOOR_TO_WALL_M)) {
      const [ce, cn] = centroidOf(own.ring);
      chips.push({
        id: `block-${code}`,
        code,
        position: enuToWorld(ce, cn, own.b.height_m + 2),
      });
    } else if (shape && d <= DOOR_TO_WALL_M) {
      const [ce, cn] = centroidOf(shape.ring);
      const len = Math.hypot(ce - e, cn - n) || 1;
      const step = Math.min(INSET_M + d, len * 0.6);
      chips.push({
        id: `block-${code}`,
        code,
        position: enuToWorld(
          e + ((ce - e) / len) * step,
          n + ((cn - n) / len) * step,
          shape.b.height_m + 2,
        ),
      });
    } else {
      // No footprint at the door (missing from OSM): mark the door itself,
      // low, rather than float over open ground.
      chips.push({
        id: `block-${code}`,
        code,
        position: enuToWorld(e, n, DOOR_CHIP_M),
      });
    }
  }

  const tourCodes = new Set(doors.keys());
  for (const { b, ring } of shapes) {
    const code = b.campus ? buildingCode(b.name) : undefined;
    if (!code || tourCodes.has(code) || ring.length < 3) continue;
    const [ce, cn] = centroidOf(ring);
    chips.push({
      id: `building-${b.id}`,
      code,
      position: enuToWorld(ce, cn, b.height_m + 2),
    });
  }
  return chips.sort((a, b) => a.code.localeCompare(b.code, 'tr'));
}
