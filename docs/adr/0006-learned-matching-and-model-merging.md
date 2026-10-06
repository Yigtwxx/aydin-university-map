# ADR-0006: Learned matching on MPS and georeferencing several models

- Status: accepted
- Date: 2026-10-06

## Context

SIFT with COLMAP registered 49 of the 97 outdoor and entrance panoramas
(`outdoor97_v1`): wide baselines between tour spots, repetitive facades and
paving. COLMAP's ONNX ALIKED + LightGlue found about four times more inliers
on hard pairs, but runs on the CPU at about 12 s per image pair, so the 9,125
pairs of the outdoor set would take about 30 hours.

## Decision

1. **Pretrained ALIKED (n16) + LightGlue from kornia, on Apple MPS.** This
   is inference only, with no training. A worker subprocess extracts features
   (0.2 s per 1300 px face) and matches the listed pairs (0.13–0.16 s per
   pair). It writes keypoints and raw matches into the COLMAP database with
   SQLite. torch and pycolmap each ship libomp and abort in one process, so
   they cannot share it. pycolmap then runs rig-aware geometric verification
   and the incremental mapper as before. Features are cached and matched
   pairs are skipped, so an interrupted run resumes. Device input tensors are
   built once and the MPS cache is emptied periodically; per-pair tensors
   leaked about 0.75 GB a minute.
2. **One georeference per model**, with three modes:
   - *aligned*: a model sharing at least 3 scenes with an already verified
     georeference takes the Sim(2) from those scenes (Umeyama);
   - *link scale*: otherwise the OSM search runs around a scale prior from
     tour spacing. The verified model's median tour link is 6.2 m. This is a
     much tighter cue than the tripod-height prior, which is about 2x off and
     inconsistent between small models;
   - *tour window*: the search centre moves to the scenes' tour coordinate
     when that coordinate is specific (T Blok). It is not used for the
     campus-wide point.
3. **The graph keeps the main connected network only.** A place on an island
   could never be routed to; islands are listed in `graph_report.json`.

## Results (`outdoor96_lg`, 96 outdoor and entrance scenes)

| | SIFT `outdoor97_v1` | LightGlue `outdoor96_lg` |
|---|---|---|
| registered scenes | 49 (models of 38 and 11) | 80 (models of 48, 15, 9, 6 and 4) |
| matching time | not recorded | 15 min extract + match, 1 min verify |
| mapping time | not recorded | 16 min |
| routable graph | 38 nodes, 4 places | 68 nodes, 17 places, 1.98 km of edges |

Model checks:
- **Model 0** (48 scenes): its geometry agrees with the verified SIFT model to
  0.02 m after a similarity. Its own OSM search fell into a wrong optimum
  (scale 0.39x the prior, 5 cameras inside buildings), so it is aligned to
  the SIFT georeference. Anchors: A 5.9 m, B 1.9 m, J 23 m.
- **Models 1 and 4**: both are anchored on D Blok entrances, at 1.6 m and
  0.5 m, with no cameras inside buildings.
- **Model 2** (T Blok garden): placed with the tour window. It connects only
  to indoor scenes, which suggests a sunken garden, so it is an island.
- **Model 3** was rejected: it places its T Blok scene 117 m from model 2.
- One "Kampüs" scene sits in models 0 and 1 with a 92° pose disagreement.
  Chaining model 1 through it would put 14 of its 15 cameras inside
  buildings, so each model keeps its own fit.

## Consequences

- Routes now cover the main gate, blocks A, B, D, E, F, G-H, J, M and O, the
  library, the hospital, the emergency and infirmary entrances and the cafe.
- 16 outdoor scenes stay unregistered, including the T Blok street entrances.
  A second matching round over spatially close pairs is the next lever.
- The J Blok anchor (23 m) is the weakest link. It needs a check against the
  panorama or a manual control point.
