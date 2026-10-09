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

1. **The campus is the interface.** The 3D map fills the screen; one floating
   card and a few slim controls sit on it, and the card is only as tall as
   what it holds.
2. **One signal colour.** Sign blue, the blue of Turkish city direction signs,
   means *your route* everywhere: the line, the step markers, the primary action
   and keyboard focus. Nothing else uses it: selected tabs are ink, a selected
   place-type chip lights up in its category's colour (`CHIP_COLORS` in
   `features/route/placeIcons.tsx`: the pin colour of its businesses, deepened
   for 4.5:1 white text, or the block, ochre or planting tone), 360° spots are
   white. The assistant's suggested questions wear the badge of the place they
   ask about in the same tones; its replies are signed with the logomark on ink.
3. **Colour from the campus.** Campus buildings wear their real ochre facades,
   neighbours stay off-white so the campus reads first, the sky is the live sky.
   Ochre is the campus accent in the interface too (entrance rims, the sun,
   the door badge of campus gates, the mark of the popular places list).
   Block letters wear one badge on the map, in the panel and on photo tiles,
   in a deep tone shared by the blocks that stand together (`block-*`).
4. **Show the place, not a list.** Places and steps carry a real 360° photo
   from the spot, so people recognise where they are going before they read.
5. **Calm, precise type.** One grotesk, three weights, sentence case, tabular
   figures for times and distances. No condensed faces, no all-caps labels.
6. **Motion answers actions.** The route draws itself when computed, the camera
   glides to it, the 360° view opens in place, the tab thumb slides. There is
   no ambient motion except the live sky, weather and the route's chevrons.
7. **The fan pattern is the signature.** The plaza's fan cobblestones become the
   logomark and the loading state, and nothing else is decorative.

## Colour

Cool, slightly blue neutrals (so the ochre campus is the warmest thing on
screen), plus the campus and signal colours. Tokens live in
`apps/web/src/app/globals.css`; shadcn's variables alias them.

| Token | Day | Night | Use |
|---|---|---|---|
| `ink` | `#0F1724` | `#EEF1F5` | text, icons, selected chips and tabs |
| `ink-muted` | `#5A6472` | `#A3ACB9` | secondary text (AA on every surface) |
| `ink-faint` | `#8A93A1` | `#6E7786` | decoration only (dots, disabled icons), never text |
| `stone` | `#E6E8EB` | `#0B1018` | app background |
| `stone-raised` | `#FFFFFF` | `#1A2230` | raised thumbs, markers, focused fields |
| `fill` / `fill-strong` | ink 5% / 8.5% | white 6% / 10% | quiet fields, chips, hovers on any surface |
| `hairline` | ink 8% | white 8% | dividers, inner edges |
| `route` | `#1F5FD6` | `#5AA2FF` | the route, the primary action, focus |
| `on-route` | `#FFFFFF` | `#07111F` | text on route blue (5.6:1 / 7.4:1) |
| `ochre` | `#DFA53C` | `#F2B84B` | campus facades, entrance rims |
| `ochre-ink` | `#1D1505` | `#1D1505` | letters on ochre, both themes |
| `block-main` | `#1E5A6B` | `#2B7689` | badges of the main building: A, B, J, N, G-H, O |
| `block-ef` | `#8A2F4F` | `#A64566` | badges of E and F |
| `block-d` / `block-m` / `block-t` | `#2E6A4A` / `#5B4391` / `#7A5232` | `#3D8560` / `#7258AD` / `#94673F` | badges of D, M, T |
| `block-other` | `#3F4756` | `#586274` | other lettered buildings (K, L, P, …); letters white on every block tone (`blockTones.ts`) |
| `ice` | `#2A8BBF` | `#A8E0FF` | the logomark's centre stone only (`ice-inverse` on ink tiles) |
| `brick` | `#C4432D` | `#E8705A` | destination pin, errors |
| `plane` / `marmara` | `#557A4C` / `#2D5D7C` | `#3E5A3C` / `#7FB0CF` | vegetation; moon, water |

Night is driven by the live sky (`data-theme="night"` on `<html>`), not by the
OS setting; every token above has both values.

## Type

- **Geist** (variable, via `next/font/google`, `latin-ext` for ı ğ ş İ) for
  everything. Weights 400 (body), 500 (labels, list titles), 600 (headings,
  numbers). Tabular figures (`.tabular`) for times, distances and steps.
- Headings track tighter: `tracking-heading` (-0.015em); the route duration
  uses `tracking-display` (-0.03em).
- Scale (px): 11 `2xs` · 12 `xs` · 13 `sm` · 14 `md` (body) · 15 `base` · 17
  `lg` · 20 `xl` · 24 `2xl` · 32 `3xl`. Line height about 1.4 for UI text,
  1.1 for the duration. Inputs are 16 px on touch screens so iOS never zooms.

## Materials

Floating UI sits on glass over the live 3D map (`src/components/glass/Glass.tsx`,
refraction adapted from React Bits' GlassSurface). Every glass surface has a
1 px light catch on the top edge, a hairline rim and a layered shadow
(`elevation-1` for controls, `elevation-2` for the panel and sheets).

| Material | Use | Look |
|---|---|---|
| `thick` | the panel: anything with body text | 82% white (84% night ink), 40 px blur, no refraction |
| `regular` | map controls, status pill, language switch | 66% white, 24 px blur, faint refractive edge (Chromium) |
| `solid` | menus that open over other glass (place search) | 94% white, so the layers never mix |
| `tint` | controls over 360° photos | 36% ink, white content, refractive edge, photo scrims behind |

**Weather sheet** (`WeatherSky.tsx`, `skyTheme.ts`): instead of glass, the
sky the map shows (weather × time of day, previews included) with white text
and a light rim. The sun and moon stay out of frame top right, behind the
weather icon; only their glow (and faint, slowly turning light shafts) reach
in. Cloud and fog are tileable Perlin textures drawn once per visit
(`skyNoise.ts`, `skyTextures.ts`), lit from above and drifting in layers at
different speeds; rain and snow fall on a canvas in three depths, the rain
slanted by the live wind (`precipitationField.ts`, `Precipitation.tsx`).
Everything stops under reduced motion. Every sky keeps 90% white text at
4.5:1, and full white text at 4.5:1 under the thickest cloud or fog
(`SKY_OVERLAY_PEAK`, tested). The status pill itself shows only the icon,
temperature and clock; the weather in words is in the sheet.

Safari and Firefox get the same tint and edge light without refraction, so
nothing depends on the effect. Popups set `bg-(--glass-bg)` (not
`bg-transparent`, which would override the material).

**Radius hierarchy** (concentric where nested): panel 22 px > card 14 px
(`rounded-card`: from/to card, photo tiles, menus) > control 10 px
(`rounded-control`: fields, buttons, block keys) > small 6–8 px (thumbnails,
badges); chips, pills and dots are round.

## Map

- **Base:** OSM ground layer (`amap export ground`): campus grounds in warm
  paving with a dashed ochre boundary, streets as white strips with casings,
  footpaths in light paving, then greenery and trees. Flat layers draw without
  depth writes in a fixed order, so they never shimmer.
- **Massing:** campus buildings in ochre, neighbours off-white, both with
  procedural window bands (darker glass by day, warm lit windows at night).
  Ambient occlusion (N8AO) grounds the blocks.
  - Surveyed blocks wear their facade recipe (`campus.toml`, colours sampled
    on the panoramas). Punched windows sit in trim-coloured surrounds on a
    projecting sill: the sill shades the wall under it, the reveal darkens the
    glass under each head, and the glass carries a little sky.
  - Cornices and string courses throw a soft shadow on the wall below them.
  - Classical blocks (A, D, G, O, the main gate's pavilions) have
    trim-coloured pilaster strips at their corners (`quoins_m`).
  - Each block stands on the ground at its lowest corner, so a terrace never
    swallows its ground floor.
- **Street furniture and planting** (`furniture.json`, `greenery.json`):
  - Lamps are the campus's black cast-iron posts, each with a cross-arm and
    two lanterns that glow at night.
  - Masts carry a red flag. Cabins are white with a band of glass. Free-
    standing boards are university blue.
  - Lawns traced on the panoramas stand 15 cm proud of the paving, inside
    their kerbs painted traffic yellow (`#E9B92E`), as on the campus.
  - Marigold beds stand a little higher than the lawn, blooms on foliage
    sides. The E court's pool is water in a white coping.
  - Campus landmarks are drawn where they stand: the seal on its stepped
    plinth and the "❤IAU" letters at the main gate, clipped topiary balls, the
    bronze rhino at the south gate, and the purple book-swap kiosk.
  - Glazed pieces (vestibules, the covered road bridge) are glass framed in
    white, never brick-coursed. Columns are round and white.
  - The boundary fence along the streets: a red-brick plinth and piers banded
    in white, black iron bars with gilded tips, a globe lamp on every pier
    that glows with the lanterns at night.
- **Sunken ground:** a terrace below the street (T Blok's garden) shows
  through an opening that the street-level layers skip (stencil). Its walls
  face into the pit.
- **Route:** a sign-blue strip with white edges and chevrons flowing towards
  the destination; it widens with distance so it never drops below ~6 px.
- **Overlays** are DOM, not WebGL, in a fixed stacking order (pins > labels >
  spots). One projector moves them every frame and fades occluded ones; they
  keep translations, tooltips and keyboard focus.
  - Block labels: a letter badge in its block's tone with a white ring; up close the name
    ("A Blok") follows in halo text (`.map-halo`: white glow by day, dark glow
    at night).
  - 360° spots: entrances are white dots with an ochre rim at every zoom
    level, named (once per place) up close; plain path spots are small neutral
    dots, only up close. Each has a 24 px hit target.
  - Start: white dot in a route-blue ring. Destination: brick pin with its
    name on a white chip, shown as soon as it is chosen. The spot open in 360°
    pulses in route blue.
  - Businesses and services (POIs, `features/map/PoiLayer.tsx`): a white
    capsule on a short tail whose tip stands on the pin, so the door's 360°
    dot stays visible below. It holds one round glyph per business at that
    spot (within 2 m), each a button that makes the business the
    destination.
    - Zoom: up close the capsule carries the business names. Further out
      only the glyphs remain, and when two capsules would touch, the nearer
      one stays. The campus overview shows none. Names give way while a
      route or a destination is shown.
    - Colours (`POI_COLORS` in `features/route/placeIcons.tsx`): one per
      kind of errand, the same by day and by night. Eat and drink orange
      `#e0701a`, shop violet `#8257e6`, health rose `#d93a6c`, library teal
      `#0f8c82`, sports green `#2f9a57`, other services slate `#5e6b80`.
      They avoid the route blue, destination brick and campus ochre. The
      glyph is white at 3:1 contrast or better.
    - A business whose storefront is not surveyed yet stands at its
      building's door (`pin_source: "entrance"`). Its tooltip and accessible
      name say so ("Bina girişi"), and the marker looks the same.
- **Framing:** the projection is offset so the camera target sits in the
  middle of the uncovered screen (right of the panel and above the 360° view
  on desktop; above the bottom sheet at its current snap on mobile, easing
  along as the sheet springs).

## Layout

Desktop (≥ 768 px):

```
┌───────────────────────────────────────────────────────────────┐
│ ┌──────────────────┐                 ☁ 19° Kapalı │ 17:54  TR EN │
│ │◠ Aydın Kampüs Fl.│                                       ┌─┐ │
│ │[Yol tarifi|Asist]│                                       │➶│ │
│ │ 🔍 Nereye gitmek… │                                       │+│ │
│ │(Bloklar)(Girişler)…                                      │−│ │
│ │ ┌──────┐┌──────┐ │          3D campus (R3F)              │2D│ │
│ │ │photo ││photo │ │                                       │⌖│ │
│ │ └──────┘└──────┘ │                                       └─┘ │
│ │ [A][B][D][E][F]  │         ┌──────────────────────────┐      │
│ └──────────────────┘         │ 360° view, glass controls│      │
│   (hugs its content)         └──────────────────────────┘      │
│                                       © OSM · 360° · weather   │
└───────────────────────────────────────────────────────────────┘
```

- **Panel:** 372 px floating card, 12 px from the edges, height follows its
  content and scrolls inside (with a soft fade at the bottom edge) only when
  needed. Brand row (28 px logomark, "Aydın Kampüs" + muted "Florya"), then a
  segmented control (Yol tarifi / Asistan) whose white thumb slides between
  tabs (`motion` `layoutId`; arrow keys move between tabs).
- **Directions, search first:** one "Nereye gitmek istiyorsunuz?" field. Once
  a place is chosen it becomes the from/to card (start ring, dotted spine,
  destination pin, swap), with the stairs-free switch below; picking a
  destination by keyboard moves focus straight to the start field.
- **Places:** category chips derived from the place directory (blocks,
  entrances, health, library, café, outdoors; only those that exist), a 2×2
  grid of photo tiles for the key places (the best-covered place of each
  category), and a keypad of block letters. A chip narrows everything to photo
  tiles of that category. Thumbnails are the 384 px front cube face of the
  place's first 360° spot, lazy loaded, with the glyph as fallback.
- **Route result:** duration (32 px), distance and step-free note, arrival
  clock time on the right, the primary "Start the 360° walk" button with a
  square "Copy link" button beside it (it widens into "Copied" for a moment),
  then a timeline: start ring → turn markers → destination pin on a route-blue
  spine.
  Each step shows a 360° thumbnail facing the walking direction; the row opens
  that step in 360° and the active step is tinted route blue.
- **Map chrome:** status pill (weather + campus clock, opens the weather and
  preview sheet) and language switch top right; below them one 40 px glass
  column: compass, zoom, 2D/3D, fit. Attribution is one quiet line in the
  bottom right corner.

Mobile (< 768 px):

```
┌──────────────────────────┐
│          19° │ 17:54 TR EN│
│                       ┌─┐│
│                       │➶││
│     3D campus,        │2D││
│     centred above     │⌖││
│     the sheet         └─┘│
│ © OSM  ⓘ Sources         │
│ ┌──────────────────────┐ │
│ │         ───          │ │  ← handle: drag, or tap to cycle
│ │ [Yol tarifi|Asistan] │ │
│ │ 🔍 Nereye gitmek…     │ │  peek ≈ 140 px
│ └──────────────────────┘ │
└──────────────────────────┘
```

- **Bottom sheet:** the same panel as a glass card 8 px from the edges, with
  three snaps: peek (140 px: handle, tabs, and the search field or the route
  summary), half (50% of the height) and full (92%, always below the status
  row). It changes height rather than sliding, so the chat input and the
  bottom fade stay on screen at every snap. Drag the handle row (or, at peek,
  anywhere on the sheet); a release projects its speed 200 ms ahead and
  springs to the nearest snap. The handle is a button: tap cycles peek → half
  → full, Arrow Up/Down step, Escape lowers one snap. Focusing a text field
  raises it to full (room for the suggestions above the keyboard); a new route
  opens it halfway; the assistant tab raises a peeking sheet to half. The
  brand row is visually hidden (still the page's heading).
- **Route summary on the sheet:** one row that leads the panel, so the peek
  shows it: duration (24 px) over distance and arrival, then the copy-link
  button and a round "Başlat" button. A copied link briefly replaces the
  distance line with "Bağlantı kopyalandı".
- **360° view:** full screen with the same glass controls and close button,
  as a dialog: focus moves to the close button, the rest of the page is inert,
  Escape or close return focus to where it was.
- **Map chrome:** the status pill shows only temperature and time; the
  control column (compass, 2D/3D, fit; zoom gives way to pinch) stays under
  it and fades out once the sheet rises into it. The OSM credit rides on top
  of the sheet, with the other sources one tap away, and hides at full.

## Shareable routes

The route lives in the URL: `?from=<nodeId>&to=<nodeId>&step=<index>&stairs=0|1`.
Opening such a link restores the route (names come from the place directory
or the graph, in the page's language; unknown ids are dropped). A new start or
destination adds a history entry; steps, the stairs switch and half-picked
routes replace the current one, so walking through steps never floods the
back button. Switching language keeps the query.

## Motion

- First load: the camera glides in from high above in 1.5 s, then the panel
  and controls fade up (400 ms, staggered by 100 ms). This is the only
  unprompted motion.
- Route computed: the line draws from start to end in 1.1 s, and the camera
  eases to fit it in 600 ms. Steps fade in with a 30 ms stagger.
- Step selected: the 360° inset crossfades in 250 ms, and the camera follows.
- Bottom sheet: snaps on a spring (about 380 ms, a hint of bounce) that keeps
  the release speed; the map's framing eases along with it.
- Interface transitions are 150–250 ms with ease-out `cubic-bezier(.2,.7,.2,1)`:
  the tab thumb slides in 220 ms, panel states crossfade in 200 ms, hovers and
  toggles take 150 ms.
- `prefers-reduced-motion`: `MotionConfig reducedMotion="user"` and a global
  CSS rule turn draws, glides and slides into instant state changes.

## Copy

Plain verbs and sentence case, written from the visitor's point of view:
"Nereye gitmek istiyorsunuz?" / "Where to?", then "Nereden başlıyorsunuz?" /
"Where are you starting from?". Errors say what happened and what to do next,
e.g. "No walkable route between these two places yet. Try a nearby entrance."
