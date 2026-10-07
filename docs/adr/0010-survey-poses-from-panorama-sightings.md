# ADR-0010: Survey every pose from sightings in the panoramas

- Status: accepted
- Date: 2026-10-07

## Context

The walking graph stood on SfM poses georeferenced to OSM footprints
(ADR-0005, ADR-0006), with a dozen hand-placed exceptions. Users found
points and entrances in the wrong place.

A triage of the tour's own arrows (`amap survey triage`) and a pilot survey
of the A Blok / main gate area showed the cause. Model m0 had squeezed that
whole area about 2.2x, so panoramas stood 10-44 m off. The T Blok model's
heading fit was ambiguous. 19 entrances had no measured position at all.
The tour's campus sketch ("Florya Yerleşke Krokisi") agrees with m0, so it
shares the squeeze and cannot arbitrate.

## Decision

Every outdoor panorama and entrance is measured again from its own pictures.
The SfM output is used only as a starting point.

- **Sightings.** For each panorama, record the horizontal angle (`ath`, the
  panorama's own degrees, independent of the pose being measured) of sharp
  vertical features:
  - OSM footprint corners (`A#2`);
  - tie points seen from several panoramas: door jambs, pillars, poles,
    signs (`r2.gate.col.n`);
  - storefronts (`poi.<slug>`).
- **Tooling.**
  - `amap look` renders any view of the local cube faces with the map drawn
    in (footprint corners, neighbours, tour arrows, solved ties).
  - `amap look snap` refines a reading to the strongest vertical edge,
    sub-degree.
  - Sightings live in per-area notebooks, `pipeline/configs/survey/*.toml`.
- **Joint robust adjustment** (`amap survey solve`, `survey/solve.py`).
  - Unknowns:
    - per SfM model, a similarity plus small per-panorama elastic offsets;
    - free panoramas: x, y, heading;
    - landmarks.
  - Losses:
    - sightings: Cauchy;
    - tour arrows: Geman-McClure, so an arrow pointing the wrong way costs a
      bounded amount;
    - priors: quadratic, except OSM corner priors, which are robust because
      OSM can be wrong.
  - Starting point: free panoramas are resected (multi-start) from known
    points, and tie points are triangulated, before a graduated
    non-convexity solve.
  - Tie points whose rays never cross at 12° or more are dropped.
  - Uncertainty comes from the Gauss-Newton covariance, scaled by the
    reduced chi-square when that is above 1. A floor is added for what no
    sighting can see: 0.3 m and 0.5°.
- **Evidence.** `amap survey report` writes one local page with:
  - acceptance checks;
  - an overview map of old to new positions with 1-sigma ellipses;
  - per panorama, the map drawn into the picture from the old and the
    solved pose.
- **Use.** `amap graph export` applies the solved poses (`pose_source =
  surveyed`) before the remaining hand overrides. The campus sketch is then
  fitted to the surveyed poses (`amap survey kroki`) to place entrances no
  picture-based solve reached.
- **Done.** Every outdoor panorama and entrance ends either proven (sighted,
  1-sigma under 1.5 m, small residuals) or listed as an open question.
  Then a walk through every entrance in the live tour confirms door-to-block
  assignments.

## Consequences

- Positions are proven, not asserted, and the evidence can be regenerated
  from the notebooks.
- OSM footprint errors show up as corners that disagree with their
  sightings. They feed the campus block registry
  (`configs/campus.toml`).
- Sighting is visual work: about 4-8 readings per panorama, done by people
  or vision-capable agents per area. The notebooks are the durable record.
- The dense mesh and SfM heights were fitted to the old poses. They stay
  as they are; they are not shipped.
