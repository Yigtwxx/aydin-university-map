/**
 * Block badge colours. Blocks that stand together share a tone, so a letter
 * says which building it opens into: the main building around the square
 * and its north deck (A, B, J, N, G-H, O, footprints 0-9 m apart, joined by
 * the deck), E and F (3 m apart), and D, M and T on their own. Deep jewel
 * tones under a white letter, apart from the route blue, the destination
 * brick and the brighter business pin colours (docs/design-system.md).
 */
const TONES = {
  main: 'bg-block-main',
  ef: 'bg-block-ef',
  d: 'bg-block-d',
  m: 'bg-block-m',
  t: 'bg-block-t',
  other: 'bg-block-other',
} as const;

const GROUP_OF: Readonly<Record<string, keyof typeof TONES>> = {
  A: 'main',
  B: 'main',
  J: 'main',
  N: 'main',
  G: 'main',
  H: 'main',
  'G-H': 'main',
  O: 'main',
  E: 'ef',
  F: 'ef',
  D: 'd',
  M: 'm',
  T: 't',
};

/** Background and letter classes of a block's badge ("A", "G-H", …). */
export function blockTone(code: string | null | undefined): string {
  const group = (code && GROUP_OF[code]) || 'other';
  return `${TONES[group]} text-block-ink`;
}
