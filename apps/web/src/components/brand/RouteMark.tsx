/**
 * Logomark: a walk from a start ring to the destination pin, what the map is
 * for. The ring and the path follow `currentColor`; the pin takes
 * `--mark-accent` (theme ice blue by default), which ink tiles and the always
 * dark 360° view override so the pin stays visible.
 */
export function RouteMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth={2.8}
        strokeLinecap="round"
      >
        <circle cx="7.9" cy="23" r="3.3" />
        <path d="M10.9 21.4c5.2-2 3.2-7.6 8.2-9.4" />
      </g>
      <path
        fill="var(--mark-accent, var(--ice))"
        fillRule="evenodd"
        d="M22.9 20c-.36 0-.7-.16-.93-.44-2.8-3.3-5.07-5.6-5.07-9.36a6 6 0 0 1 12 0c0 3.76-2.27 6.06-5.07 9.36-.23.28-.57.44-.93.44zm0-7.6a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4z"
      />
    </svg>
  );
}
