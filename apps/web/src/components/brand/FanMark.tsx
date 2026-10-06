/**
 * Logomark from the plaza's fan-shaped cobblestones (coda di pavone):
 * three nested arcs opening upwards, like the paving seen from above.
 */
export function FanMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden fill="none">
      <path
        d="M4 26a12 12 0 0 1 24 0"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path
        d="M9 26a7 7 0 0 1 14 0"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path
        d="M14 26a2 2 0 0 1 4 0"
        stroke="var(--ochre)"
        strokeWidth="2.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
