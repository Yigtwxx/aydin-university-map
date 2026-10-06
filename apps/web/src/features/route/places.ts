import type { Place } from '@/features/campus/queries';

/**
 * Quick-filter categories, derived from the place directory itself: building
 * entrances carry a block letter, the rest are told apart by their names
 * (Turkish and English, so either locale's data works).
 */
export type PlaceCategory =
  'blocks' | 'gates' | 'health' | 'library' | 'cafe' | 'outdoor';

export const CATEGORY_ORDER: readonly PlaceCategory[] = [
  'blocks',
  'gates',
  'health',
  'library',
  'cafe',
  'outdoor',
];

const NAME_RULES: [PlaceCategory, RegExp][] = [
  ['health', /acil|hastane|revir|sağlık|emergency|hospital|infirmary|health/i],
  ['library', /kütüphane|library/i],
  ['cafe', /kafe|cafe|café|kantin|yemekhane|restoran|canteen/i],
];

export function categoryOf(place: Place): PlaceCategory {
  if (place.building) return 'blocks';
  const names = `${place.name_tr} ${place.name_en}`;
  for (const [category, pattern] of NAME_RULES)
    if (pattern.test(names)) return category;
  return place.kind === 'entrance' ? 'gates' : 'outdoor';
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
    if (category === 'blocks' || category === 'outdoor') continue;
    const best = byCoverage.find((p) => categoryOf(p) === category);
    if (best) picked.push(best);
  }
  for (const place of byCoverage) {
    if (picked.length >= limit) break;
    if (!picked.includes(place) && categoryOf(place) !== 'blocks')
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
