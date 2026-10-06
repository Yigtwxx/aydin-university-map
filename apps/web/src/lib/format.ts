export type Locale = "tr" | "en";

const numberFormat = (locale: Locale, digits: number) =>
  new Intl.NumberFormat(locale === "tr" ? "tr-TR" : "en-GB", {
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
  return locale === "tr" ? `${minutes} dk` : `${minutes} min`;
}
