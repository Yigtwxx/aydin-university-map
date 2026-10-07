/**
 * Tileable fractal Perlin noise for the weather sheet's fog and cloud. The
 * lattice wraps, so a texture drawn from it repeats without a seam and can
 * drift forever by sliding one copy into the next.
 */

/** Deterministic PRNG (mulberry32): the same sky every visit. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const GRADIENTS = 256;

function gradientTable(seed: number) {
  const next = random(seed);
  const gx = new Float32Array(GRADIENTS);
  const gy = new Float32Array(GRADIENTS);
  for (let i = 0; i < GRADIENTS; i++) {
    const angle = next() * Math.PI * 2;
    gx[i] = Math.cos(angle);
    gy[i] = Math.sin(angle);
  }
  const perm = new Uint8Array(GRADIENTS);
  for (let i = 0; i < GRADIENTS; i++) perm[i] = i;
  for (let i = GRADIENTS - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [perm[i], perm[j]] = [perm[j]!, perm[i]!];
  }
  return { gx, gy, perm };
}

const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);

/**
 * Perlin noise in about [-1, 1] at (x, y), periodic with `periodX` by
 * `periodY` lattice cells.
 */
function perlin(
  table: ReturnType<typeof gradientTable>,
  x: number,
  y: number,
  periodX: number,
  periodY: number,
): number {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = x - x0;
  const fy = y - y0;
  const wrap = (v: number, p: number) => ((v % p) + p) % p;
  const ix0 = wrap(x0, periodX);
  const ix1 = wrap(x0 + 1, periodX);
  const iy0 = wrap(y0, periodY);
  const iy1 = wrap(y0 + 1, periodY);
  const { gx, gy, perm } = table;
  const dot = (ix: number, iy: number, dx: number, dy: number) => {
    const g = perm[(perm[ix & 255]! + iy) & 255]!;
    return gx[g]! * dx + gy[g]! * dy;
  };
  const u = fade(fx);
  const v = fade(fy);
  const a = dot(ix0, iy0, fx, fy);
  const b = dot(ix1, iy0, fx - 1, fy);
  const c = dot(ix0, iy1, fx, fy - 1);
  const d = dot(ix1, iy1, fx - 1, fy - 1);
  const top = a + (b - a) * u;
  const bottom = c + (d - c) * u;
  return (top + (bottom - top) * v) * Math.SQRT2;
}

export interface NoiseOptions {
  width: number;
  height: number;
  /** Lattice cells across the width and height at the coarsest octave. */
  cellsX: number;
  cellsY: number;
  octaves: number;
  seed: number;
}

/**
 * Fractal noise in [0, 1], `width` × `height`, that tiles in both directions.
 * Each octave doubles the cells and halves the weight.
 */
export function tileableNoise({
  width,
  height,
  cellsX,
  cellsY,
  octaves,
  seed,
}: NoiseOptions): Float32Array {
  const table = gradientTable(seed);
  const out = new Float32Array(width * height);
  let norm = 0;
  for (let o = 0; o < octaves; o++) norm += 0.5 ** o;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let sum = 0;
      for (let o = 0; o < octaves; o++) {
        const scale = 2 ** o;
        const px = cellsX * scale;
        const py = cellsY * scale;
        sum +=
          perlin(table, (x / width) * px, (y / height) * py, px, py) * 0.5 ** o;
      }
      out[y * width + x] = Math.min(1, Math.max(0, 0.5 + (sum / norm) * 0.5));
    }
  }
  return out;
}
