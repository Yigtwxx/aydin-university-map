import { Color } from 'three';

/**
 * Scene colours, taken from the campus itself (docs/design-system.md):
 * ochre facades, warm paving, and the blue of Turkish city direction signs
 * for the route, which also keeps it legible against the yellow buildings.
 */
export const palette = {
  ink: '#131A24',
  route: '#1F5FD6',
  routeEdge: '#FFFFFF',
  brick: '#B2432F',
  ochre: '#DFA53C',
  fog: '#DCE4EA',
  hemiSky: '#EAF2F7',
  hemiGround: '#B8AE98',
  ground: '#E4E1DA',
  edges: '#B3A88F',
} as const;

export const groundColors = {
  areas: {
    campus: '#F3EAD3',
    pedestrian: '#EDE4D0',
    parking: '#D8D4CA',
    pitch: '#94BD7C',
    water: '#8FB4C9',
  },
  casing: { major: '#BDB4A0', minor: '#C9C1AF', path: '#D8C9AC' },
  fill: { major: '#FFFFFF', minor: '#FFFFFF', path: '#F8F0DE' },
  campusOutline: '#C48E2C',
  /** Street paint: a shade darker than the white street fill. */
  marking: '#D5CEC0',
  pitchLine: '#F7F6F0',
} as const;

/**
 * Render order of the flat ground layers (all drawn without depth writes, so
 * the order alone decides what sits on top; see GroundLayer).
 */
export const layers = {
  /** Lift above the base ground (m); with DepthRange's near plane it beats depth precision. */
  lift: 0.05,
  areas: 1,
  greenery: 2,
  casing: 3,
  /** Road fills take 4-6 (paths, minor, major). */
  roads: 4,
  markings: 7,
  outline: 8,
  routeShadow: 9,
  route: 10,
} as const;

/**
 * Flat overlays never write depth and are pulled a constant step towards the
 * camera. No slope factor: it grows with distance and at the overview pulled
 * the paving over the 15 cm lawns and the feet of the furniture.
 */
export const OVERLAY = {
  depthWrite: false,
  polygonOffset: true,
  polygonOffsetFactor: 0,
  polygonOffsetUnits: -2,
} as const;

export const buildingColors = {
  campusWall: new Color('#F0BF56'),
  campusRoof: new Color('#EADDC2'),
  otherWall: new Color('#F2F2F0'),
  otherRoof: new Color('#E4E4E1'),
} as const;

export const CAMPUS_LAT = 40.9915;
export const CAMPUS_LNG = 28.7971;
