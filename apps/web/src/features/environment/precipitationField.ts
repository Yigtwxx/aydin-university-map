/**
 * Rain and snow for the weather sheet, as particles at three depths: far
 * drops are short, slow and faint, near ones long, fast and bright, which is
 * what makes a flat panel read as falling weather. Pure state; the canvas in
 * Precipitation.tsx draws it.
 */

export type PrecipitationKind = 'rain' | 'snow';

export const LAYERS = 3;

export interface Particle {
  x: number;
  y: number;
  /** Depth band, 0 (far) to LAYERS - 1 (near). */
  layer: number;
  /** Per-particle variation of size and speed, about 0.8–1.2. */
  jitter: number;
  /** Phase of a snowflake's sway. */
  phase: number;
}

interface Depth {
  /** Fall speed, px/s. */
  speed: number;
  /** Streak length (rain) or radius (snow), px. */
  size: number;
  alpha: number;
  /** Share of the particles at this depth. */
  share: number;
}

export const DEPTHS: Record<PrecipitationKind, readonly Depth[]> = {
  rain: [
    { speed: 560, size: 8, alpha: 0.14, share: 0.5 },
    { speed: 820, size: 14, alpha: 0.24, share: 0.32 },
    { speed: 1120, size: 22, alpha: 0.38, share: 0.18 },
  ],
  snow: [
    { speed: 22, size: 0.9, alpha: 0.45, share: 0.5 },
    { speed: 36, size: 1.5, alpha: 0.7, share: 0.32 },
    { speed: 54, size: 2.3, alpha: 0.9, share: 0.18 },
  ],
};

/** Particles per 10 000 px² at full intensity. */
const DENSITY: Record<PrecipitationKind, number> = { rain: 11, snow: 7 };

/** Sideways drift of a snowflake's sway, px/s. */
const SWAY = 14;

export interface Field {
  kind: PrecipitationKind;
  particles: Particle[];
  width: number;
  height: number;
  /** 0–1: drizzle to downpour. */
  intensity: number;
  /** Sideways travel per px of fall from the wind, about -0.45–0.45. */
  wind: number;
  random: () => number;
}

export function createField(
  kind: PrecipitationKind,
  intensity: number,
  wind: number,
  random: () => number = Math.random,
): Field {
  return {
    kind,
    particles: [],
    width: 0,
    height: 0,
    intensity,
    wind,
    random,
  };
}

function pickLayer(kind: PrecipitationKind, roll: number): number {
  let sum = 0;
  const depths = DEPTHS[kind];
  for (let i = 0; i < depths.length; i++) {
    sum += depths[i]!.share;
    if (roll < sum) return i;
  }
  return depths.length - 1;
}

/** The wind's slant at `t` seconds: steady, with slow gusts. */
export function slantAt(field: Field, t: number): number {
  if (field.kind === 'snow') return field.wind * 0.3;
  return field.wind + 0.05 * Math.sin(t * 0.6) + 0.025 * Math.sin(t * 1.7 + 1);
}

/**
 * How far beyond each side a particle may be and still drift into view: the
 * wind's whole sideways travel over the height, plus room for gusts and sway.
 */
function margins(field: Field): { left: number; right: number } {
  const lead = Math.abs(field.wind) * field.height;
  const slack = 0.1 * field.height + 40;
  return {
    left: (field.wind > 0 ? lead : 0) + slack,
    right: (field.wind < 0 ? lead : 0) + slack,
  };
}

/** A particle somewhere above the top edge, placed so the wind carries it in. */
function spawn(field: Field, particle: Particle, anywhere: boolean) {
  const { width, height, random } = field;
  const lead = Math.abs(field.wind) * height;
  particle.x = random() * (width + lead) - (field.wind > 0 ? lead : 0);
  particle.y = anywhere ? random() * height : -random() * 60 - 20;
}

/** Resizes the field and keeps its particle count to the new area. */
export function resizeField(field: Field, width: number, height: number) {
  field.width = width;
  field.height = height;
  const count = Math.round(
    ((width * height) / 10_000) * DENSITY[field.kind] * field.intensity,
  );
  const { particles, random } = field;
  while (particles.length > count) particles.pop();
  while (particles.length < count) {
    const particle: Particle = {
      x: 0,
      y: 0,
      layer: pickLayer(field.kind, random()),
      jitter: 0.8 + random() * 0.4,
      phase: random() * Math.PI * 2,
    };
    spawn(field, particle, true);
    particles.push(particle);
  }
}

/** Advances every particle by `dt` seconds; those that leave fall again. */
export function stepField(field: Field, dt: number, t: number) {
  const slant = slantAt(field, t);
  const depths = DEPTHS[field.kind];
  const { left, right } = margins(field);
  for (const particle of field.particles) {
    const depth = depths[particle.layer]!;
    const fall = depth.speed * particle.jitter * dt;
    particle.y += fall;
    particle.x += fall * slant;
    if (field.kind === 'snow')
      particle.x +=
        Math.sin(t * (0.6 + particle.jitter * 0.5) + particle.phase) *
        SWAY *
        (particle.layer + 1) *
        0.5 *
        dt;
    const out =
      particle.y - depth.size * 2 > field.height ||
      particle.x < -left ||
      particle.x > field.width + right;
    if (out) spawn(field, particle, false);
  }
}
