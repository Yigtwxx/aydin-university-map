# ADR-0005: Georeference SfM models against OSM with free-space constraints

- Status: accepted
- Date: 2026-10-06

## Context

The tour gives no compass heading (`p28` is not one, ADR-0003) and only
building-level coordinates. The metric scale from the tripod height was a
prior with 21-22 % spread. The model -> map transform (yaw, scale, shift
after gravity levelling) must come from geometry against OpenStreetMap.

First attempts scored only how close reconstructed facade points (0.5-3 m above
ground) fall to building outlines. Every top candidate then put 50-70 % of the
cameras inside buildings, and the spike model landed among small residential
blocks: dense neighbourhoods have outlines everywhere, so they win on outline
proximity alone. Filtering by plausibility afterwards could not help, because
the right placement never entered the candidate pool.

## Decision

For every yaw (2° steps) and scale, the shift is chosen by FFT cross-correlation
of a combined objective:

    mean outline proximity of facade points
    - 1.0 x fraction of facade points inside buildings (outline-eroded interior)
    - 2.0 x fraction of cameras inside buildings

The best peaks are then ranked by these plausibility checks:
- cameras outside footprints
- tour walking links do not cross footprints
- semantic anchors: entrance panoramas named "<X> Blok Giriş" lie next to the
  OSM building named "İstanbul Aydın Üniversitesi <X> Binası"

The winner is refined with trimmed 2D ICP with scale. The scale search spans
0.35-1.3x the tripod prior.

## Result (outdoor model, 38 panoramas)

| | |
|---|---|
| Yaw / scale | 33.6°, 4.80 m per model unit (0.50x the tripod prior) |
| ICP RMS | 0.72 m (44.6 % inliers; the rest are trees and street furniture) |
| Cameras inside buildings | 1 of 38 (a doorway entrance pano) |
| Links crossing buildings | 0 % |
| A Blok entrance to A Binası | 5.9 m |
| Agreement | all top-8 candidates within ±3° and ±8 m; no rival yaw |

## Consequences

- The tripod-height prior is biased about 2x high, because low facade points pass
  as ground. It stays only as a coarse prior. The metric scale comes from the
  OSM fit, and true link spacing is about 6.5 m (median).
- OSM maps only A/B/D/J/N by name and misses some campus blocks. The free-space
  terms keep this from mattering near the plaza, but models far from mapped
  buildings may need a manual control point.
- Search takes about 80 s per model on the M4 Pro (10 scales x 180 yaws).
