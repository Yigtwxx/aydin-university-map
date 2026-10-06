export type Locale = 'tr' | 'en';

const numberFormat = (locale: Locale, digits: number) =>
  new Intl.NumberFormat(locale === 'tr' ? 'tr-TR' : 'en-GB', {
    maximumFractionDigits: digits,
  });

/** Walking distance: metres below 1 km (rounded to 5 m), kilometres above. */
export function formatDistance(metres: number, locale: Locale): string {
  if (metres < 1000) {
    const rounded =
      metres < 10 ? Math.round(metres) : Math.round(metres / 5) * 5;
    return `${rounded} m`;
  }
  return `${numberFormat(locale, 1).format(metres / 1000)} km`;
}

/** Walking time: at least one minute, whole minutes. */
export function formatDuration(seconds: number, locale: Locale): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return locale === 'tr' ? `${minutes} dk` : `${minutes} min`;
}

/** U+2212, the typographic minus: "−1. kat" reads better than "-1. kat". */
const MINUS = '−';

/**
 * A storey as a phrase: "zemin kat", "2. kat", "−1. kat" / "ground floor",
 * "floor 2", "floor −1". Capitalise it for badges with `sentenceCase`.
 */
export function formatFloor(floor: number, locale: Locale): string {
  const n = floor < 0 ? `${MINUS}${Math.abs(floor)}` : String(floor);
  if (locale === 'tr') return floor === 0 ? 'zemin kat' : `${n}. kat`;
  return floor === 0 ? 'ground floor' : `floor ${n}`;
}

/** First letter upper-cased with the locale's rules (Turkish i -> İ). */
export function sentenceCase(text: string, locale: Locale): string {
  const tag = locale === 'tr' ? 'tr-TR' : 'en-GB';
  return text.charAt(0).toLocaleUpperCase(tag) + text.slice(1);
}
