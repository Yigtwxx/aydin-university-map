# Design system: Aydın Campus Map

## Brief

- **Subject:** İstanbul Aydın University's Florya campus. Ochre-yellow facades
  with brick-red trims, a plaza paved in fan-shaped cobblestones (*coda di
  pavone*), plane trees, and an aviation faculty next to the old airport.
- **Audience:** students, visitors and staff, mostly on desktop (desktop-first,
  mobile fully supported).
- **Primary job:** pick where you are and where you want to go, see the
  shortest walking route on the 3D campus, and preview it in 360°.

## Principles

1. **The campus is the interface.** The 3D map fills the screen; controls dock
   to its edges and stay thin.
2. **One signal colour.** Sign blue, the blue of Turkish city direction signs,
   means *your route* everywhere: the line, the step markers, the primary action.
   It also stays legible against the ochre campus facades. Nothing else uses it.
3. **Colour from the campus.** Campus buildings wear their real ochre facades,
   neighbours stay off-white so the campus reads first, the sky is the live sky.
4. **Read like wayfinding signage.** Directions are short, condensed and big:
   a turn, a distance, a landmark. Numbers are tabular.
5. **Motion answers actions.** The route draws itself when computed, the camera
   glides to it, the 360° view opens in place. There is no ambient motion
   except the live sky, weather and the route's flowing chevrons.
6. **The fan pattern is the signature.** The plaza's fan cobblestones become the
   logomark and the loading state, and nothing else is decorative.

## Colour

| Token | Day | Night | Use |
|---|---|---|---|
| `ink` | `#131A24` | `#ECEEE9` | text, icons |
| `stone` | `#E9E7E1` | `#0F1520` | app background (paving stone / night sky) |
| `stone-raised` | `#FBFAF7` | `#1A2230` | paper: fields, labels, glass tint |
| `stone-deep` | `#D5D2C9` | `#2A3445` | borders |
| `route` | `#1F5FD6` | `#5AA2FF` | the route, the primary action, focus (Turkish direction-sign blue) |
| `ochre` | `#DFA53C` | `#F2B84B` | campus facades, building badges, brand mark, sun |
| `brick` | `#B2432F` | `#E0705A` | destination pin, errors |
| `plane` | `#557A4C` | `#3E5A3C` | vegetation, open-campus places |
| `marmara` | `#2D5D7C` | `#7FB0CF` | moon, water |

All text/background pairs meet WCAG AA (white on route blue is 5.6:1). Ochre is never used for body text on stone; text on ochre badges stays dark in both themes.

## Type

- **Barlow Condensed** (600/700): headings, direction text, distances and
  times (tabular figures). Sentence case, never all caps.
- **Atkinson Hyperlegible Next** (400/600): UI and body text.
- Scale (1.25): 13 / 16 / 20 / 25 / 31 / 39 / 49 px, body line-height 1.5,
  headings 1.1. Line length at most 70 characters.

## Materials

Floating UI sits on glass over the live 3D map (`src/components/glass/Glass.tsx`,
refraction adapted from React Bits' GlassSurface):

| Material | Use | Look |
|---|---|---|
| `thick` | directions panel, status sheet: anything with body text | 80% paper tint, 28–30 px blur, elevation 2, no edge refraction |
| `regular` | map controls, status pill, language switch | 58% paper tint, 18 px blur, refractive edge (Chromium) |
| `tint` | controls over 360° photos | 30% ink tint, white content, refractive edge, photo scrims behind |

Safari and Firefox get the same tint and edge light without refraction, so
nothing depends on the effect. Radii follow hierarchy: panels 28, sheets 22,
groups 16, pills and dots fully round.

## Map

- **Base:** OSM ground layer (`amap export ground`): campus grounds in warm
  paving with a dashed ochre boundary, streets as white strips with casings,
  footpaths in light paving, then greenery and trees. Flat layers draw without
  depth writes in a fixed order, so they never shimmer.
- **Massing:** campus buildings in ochre, neighbours off-white, both with
  procedural window bands (darker glass by day, warm lit windows at night).
  Ambient occlusion (N8AO) grounds the blocks.
- **Route:** a sign-blue strip with white edges and chevrons flowing towards
  the destination; it widens with distance so it never drops below ~6 px.
- **Overlays** are DOM, not WebGL: building labels (ochre letter badge),
  start dot, destination pin with its name, 360° spots and the focus pulse.
  One projector moves them every frame; they keep translations, tooltips and
  keyboard focus.
- **Framing:** the projection is offset so the camera target sits in the
  middle of the uncovered screen (right of the panel, above the 360° view).

## Layout (desktop)

```
┌───────────────────────────────────────────────────────────────┐
│ ┌─────────────┐                    ☁ 21° Kapalı │ 14:12  TR EN │
│ │◠ Aydın …    │                                               │
│ │ ◉ From      │                                          (N)  │
│ │ ◆ To     ⇅  │          3D campus (R3F)                  +   │
│ │ [no stairs] │                                           −   │
│ │┌───────────┐│                                           2D  │
│ ││ 1 min     ││          ┌──────────────────────────┐     ⌖   │
│ ││ ▶ 360°    ││          │ 360° view, glass controls│         │
│ │└───────────┘│          │      ‹  • • •  ›         │         │
│ │ steps…      │          └──────────────────────────┘         │
│ └─────────────┘                         attributions          │
└───────────────────────────────────────────────────────────────┘
```

The route summary is a direction sign: white condensed type on sign blue with
an inset white border. The status pill opens a sheet with live weather and a
preview (time of day slider, weather chips, back to live). On mobile the panel
becomes a bottom sheet.

## Motion

- First load: the camera glides in from high above in 1.5 s, then panels
  slide in (150–300 ms staggered). This is the only unprompted motion.
- Route computed: the line draws from start to end in 1.1 s, and the camera
  eases to fit it in 600 ms.
- Step selected: the 360° inset crossfades in 250 ms, and the camera follows.
- Durations are 150 / 250 / 400 / 800 ms with ease-out `cubic-bezier(.2,.7,.2,1)`.
- `prefers-reduced-motion`: there are no draws or glides, only instant state
  changes.

## Copy

Plain verbs and sentence case, written from the visitor's point of view:
"Where are you?" / "Where to?". Errors say what happened and what to do next,
e.g. "No walkable route between these two places yet. Try a nearby entrance."
