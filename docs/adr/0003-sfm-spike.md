# ADR-0003: SfM spike result — go with cube-face rig SfM

- Status: accepted
- Date: 2026-10-06

## Context

Phase 1 had to prove that metric camera poses can be recovered from the tour's
cube-face panoramas on an Apple Silicon Mac, with classical SfM and no model
training. Spike set: 35 connected outdoor/entrance scenes found by BFS from the
"Kampüs" hub (`amap tour select --hub scene_428523 --n 35`).

Setup: pycolmap 4.2.1 (CPU SIFT), each panorama = rig of 5 pinhole sensors
(f, r, b, l, d; the sky-dominated up face is dropped outdoors), pairs from tour
links up to 2 hops (156 scene pairs, 3,900 image pairs), incremental mapper with
fixed intrinsics and fixed sensor-from-rig.

## Results (M4 Pro, 14 cores)

| Gate | Criterion | Result | |
|---|---|---|---|
| G1 | one consistent face orientation | all 6 faces `id`, 12/12 scenes, best/2nd margin 3-17x, worst median seam ratio 1.70 | pass |
| G2 | ≥ 32/35 panos in one model | 30/35 (30/30 of visually connected scenes) | fail as written, see below |
| G3 | reproj ≤ 1.5 px, track ≥ 3 | 0.555 px, 4.19 | pass |
| G4 | camera-height CV ≤ 15 %, link median 3-25 m | CV 21 %, median link 12.5 m, no link > 60 m | partial |
| G5 | ≤ 2 h | 79 s total (extract 21 s, match 53 s, map 3 s) | pass |

Levelling: the panoramas are levelled to a median 0.76° from the common gravity
direction, so the rig down axis is a reliable gravity prior.

### Why five scenes did not register

All five are leaf entrances reached through a single link:

- *Uçak Teknoloji Merkezi Giriş*, *Tıp Fakültesi Hastanesi Giriş*, *Yurt Giriş*:
  "teleport" links from the campus gate hub to buildings 149-610 m away. They have
  no visual overlap with the hub, so not registering them is correct.
- *Konferans Salonu Giriş*: actually an indoor corridor (the keyword "Giriş"
  misled the classifier); one doorway link is not enough overlap.
- *Otopark Giriş*: a street scene outside the campus, far from the gate.

## Findings that change the design

1. **Tour links are not all walkable.** Some are teleports between distant places.
   The walking graph must keep only links confirmed by SfM geometry (both panos in
   the same model, plausible length) and flag the rest; scene sets for SfM should
   not grow through teleport hubs.
2. **The nadir is patched** (no tripod, cloned paving texture) and never matches
   across panoramas: zero 3D observations in down faces. The nadir mask stays, and
   the down face only contributes near-horizon ground.
3. **Scale from camera height is noisy** (CV 21 % with distant ground features,
   7.44 m/unit). It is kept as a prior, and Phase 2 estimates the metric scale
   independently from the OSM footprint alignment; the two must agree within 10 %.
4. **`p28` is not a compass heading** (median residual 46.8° against SfM yaw).
   Headings will come from the georeference only.
5. Runtime is not a constraint: the full 424-pano set is expected to take minutes
   for sparse SfM, not hours.

## Decision

Go. Continue with Phase 2 using the same rig SfM, adding teleport-link filtering,
the classifier override for indoor "Giriş" scenes, and OSM-based scale/georeference.
