import type { Place } from '@/features/campus/queries';

/** A business or service's own category (`PlaceOut.category`). */
export type PoiCategory = NonNullable<Place['category']>;

/**
 * Quick-filter categories, derived from the place directory itself:
 * businesses and services carry their own category; otherwise rooms are
 * indoors, building entrances carry a block letter, and the rest are told
 * apart by their names (Turkish and English, so either locale's data works).
 */
export type PlaceCategory =
  | 'blocks'
  | 'gates'
  | 'health'
  | 'library'
  | 'eat'
  | 'shop'
  | 'services'
  | 'outdoor'
  | 'rooms';

export const CATEGORY_ORDER: readonly PlaceCategory[] = [
  'blocks',
  'gates',
  'health',
  'library',
  'eat',
  'shop',
  'services',
  'outdoor',
  'rooms',
];

/** Which chip a business files under: what people go there for. */
export const POI_CHIP: Record<PoiCategory, PlaceCategory> = {
  food: 'eat',
  cafe: 'eat',
  shop: 'shop',
  health: 'health',
  library: 'library',
  student_services: 'services',
  atm: 'services',
  sports: 'services',
  parking: 'services',
  service: 'services',
};

const NAME_RULES: [PlaceCategory, RegExp][] = [
  ['health', /acil|hastane|revir|sağlık|emergency|hospital|infirmary|health/i],
  ['library', /kütüphane|library/i],
  ['eat', /kafe|cafe|café|kantin|yemekhane|restoran|canteen/i],
];

export function categoryOf(place: Place): PlaceCategory {
  if (place.category) return POI_CHIP[place.category];
  if (place.kind === 'indoor') return 'rooms';
  // A block's garden names the block too, but only doors are block keys.
  if (place.building && place.kind === 'entrance') return 'blocks';
  const names = `${place.name_tr} ${place.name_en}`;
  for (const [category, pattern] of NAME_RULES)
    if (pattern.test(names)) return category;
  return place.kind === 'entrance' ? 'gates' : 'outdoor';
}

/**
 * A business or service with a map pin: at its storefront, or at its
 * building's measured door until the storefront is measured
 * (`pin_source: 'entrance'`).
 */
export type PinnedPoi = Place & {
  category: PoiCategory;
  pin_enu: [number, number];
};

export function isPinnedPoi(place: Place): place is PinnedPoi {
  return Boolean(place.category && place.pin_enu);
}

/** The places the map pins: businesses and services with a pin. */
export function pinnedPois(places: readonly Place[]): PinnedPoi[] {
  return places.filter(isPinnedPoi);
}

/** Pins closer than this stand at one spot (often one door), metres. */
export const SAME_SPOT_M = 2;

/** Businesses pinned at one spot: one marker on the map. */
export interface PoiGroup {
  /** Its first business's id. */
  id: string;
  pin: [number, number];
  places: PinnedPoi[];
}

/**
 * The map's business markers: pins at one spot (the businesses behind one
 * door) share a marker, in directory order, so none hides another for good.
 */
export function poiGroups(places: readonly Place[]): PoiGroup[] {
  const groups: PoiGroup[] = [];
  for (const place of pinnedPois(places)) {
    const [e, n] = place.pin_enu;
    const group = groups.find(
      ({ pin }) => Math.hypot(pin[0] - e, pin[1] - n) < SAME_SPOT_M,
    );
    if (group) group.places.push(place);
    else groups.push({ id: place.id, pin: place.pin_enu, places: [place] });
  }
  return groups;
}

/** Id prefix of a business with no panorama of its own (routed to a nearby one). */
export const POI_PLACE_PREFIX = 'poi:';

/**
 * Where the map shows a business's own panoramas: at its pin, for the spots
 * that only borrow a position (`borrowed`: indoor spots stand at the
 * entrance they hang off). A business of its own (`poi:` id) only names a
 * nearby spot, which keeps its place.
 */
export function pinnedSpots(
  places: readonly Place[],
  borrowed: (nodeId: string) => boolean,
): Map<string, [number, number]> {
  const spots = new Map<string, [number, number]>();
  for (const place of pinnedPois(places)) {
    if (place.id.startsWith(POI_PLACE_PREFIX)) continue;
    for (const id of place.node_ids)
      if (borrowed(id)) spots.set(id, place.pin_enu);
  }
  return spots;
}

/** Categories that have at least one place, in display order. */
export function presentCategories(places: Place[]): PlaceCategory[] {
  const present = new Set(places.map(categoryOf));
  return CATEGORY_ORDER.filter((c) => present.has(c));
}

/** The panorama that represents a place (its first graph node). */
export function sceneOf(place: Place): string {
  return place.node_ids[0] ?? place.id;
}

/**
 * Places worth a photo tile before the visitor types: the best-covered place
 * of each non-block category (more 360° spots means a bigger, better-known
 * place), so the main gate beats a side door and the hospital beats a ward.
 */
export function highlightsOf(places: Place[], limit = 4): Place[] {
  const byCoverage = [...places].sort(
    (a, b) => b.node_ids.length - a.node_ids.length,
  );
  const picked: Place[] = [];
  for (const category of CATEGORY_ORDER) {
    if (category === 'blocks' || category === 'outdoor' || category === 'rooms')
      continue;
    const best = byCoverage.find((p) => categoryOf(p) === category);
    if (best) picked.push(best);
  }
  for (const place of byCoverage) {
    if (picked.length >= limit) break;
    const category = categoryOf(place);
    if (
      !picked.includes(place) &&
      category !== 'blocks' &&
      category !== 'rooms'
    )
      picked.push(place);
  }
  return picked.slice(0, limit);
}

const collator = new Intl.Collator('tr', { numeric: true });

/** Building entrances in block-letter order (A, B, …, G-H, …). */
export function blockEntrances(places: Place[]): Place[] {
  return places
    .filter((p) => categoryOf(p) === 'blocks')
    .sort((a, b) => collator.compare(a.building ?? '', b.building ?? ''));
}
