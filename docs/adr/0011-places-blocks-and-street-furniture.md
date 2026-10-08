# ADR-0011: Businesses, block registry and street furniture as curated data

- Status: accepted
- Date: 2026-10-07

## Context

The map knew panoramas, OSM footprints and the tour's labels. People also
look for:

- businesses and services: Starbucks, the infirmary, the library;
- the campus blocks by their letters: OSM names only 7 of them and draws
  some as one footprint;
- what they walk past and over: stairs, terraces, railings, benches, café
  terraces.

The tour is years old, so some businesses have closed or moved since it was
shot.

## Decision

Three notebooks under `pipeline/configs/` hold curated facts with their
evidence, and the pipeline turns each into a published asset with a contract
in `packages/contracts`.

- **Points of interest** (`pois.toml` → `pois.json`, `amap_contracts.pois`).
  - A POI enriches the place its panorama already is: category, brand,
    aliases, pin.
  - A POI without a panorama of its own becomes a `poi:<slug>` place that
    `/route` resolves.
  - The pin stands at the surveyed storefront (`poi.<slug>` tie point). Until
    then it stands at its building's measured door, and
    `pin_source = entrance` says so.
  - Each POI carries a web-checked status and date. Closed ones keep their
    tour label out of search.
  - Places the tour does not show are not added: the tour is the data.
- **Campus block registry** (`campus.toml` → `buildings.json` fields `code`,
  `facade`, `base_m`; `geo/campus.py`).
  - Which footprint is which block; split footprints; outlines that replace
    wrong OSM ones; measured heights.
  - Facade recipes (`amap_contracts.facade`), from colours sampled on the
    panoramas and window rhythm counted on the walls.
  - Names keep the "İstanbul Aydın Üniversitesi X Binası" form every reader
    already recognises.
- **Street furniture** (`furniture.toml` → `furniture.json`,
  `amap_contracts.furniture`): terraces with their edges, stairs, ramps,
  railings, items and café seating groups.
  - **Proposals:** OWLv2 detections (`amap furniture detect`, inference
    only) are kept as panorama angles, so they survive pose corrections.
  - **Placement:** detections are placed by bearing triangulation across
    panoramas, which needs no camera height, or by monoplot when seen once.
  - **Review:** proposals are reviewed before they enter the notebook.
  - **Tripod height:** comparing triangulated and monoplot ranges measures
    the camera height.
  - **Routing:** an outdoor walking edge over a flight becomes a stairs
    edge, so step-free routes avoid it.
  - **Landmarks:** a second query set (`--queries landmarks`: masts, cabins,
    boards, trees) proposes the bigger outdoor objects the same way.
- **Planting** (`greenery.toml` → `greenery.json`): lawns traced on the
  ground orthomosaic and trees seen on the panoramas, added to OSM's (a tree
  within 1.5 m of an OSM one is that tree).
  - Flower beds (`kind = "flowerbed"`) and pools (`kind = "pool"`) are traced
    the same way.
  - All traced areas render as one vertex-coloured mesh per kind. One
    material per area would leave every area after the second undrawn.
- **Landmarks and kiosks** are item kinds of their own, because a recolour
  would not read: `kiosk`, `emblem` (length = diameter), `letters` (length =
  word width), `topiary`, `statue` and `stand`.
- **The boundary fence** is a railing with `style = "fence"`, traced on the
  panoramas (OSM has no barrier lines here). Its piers (at corners, at most
  3 m apart) and their globe lamps are generated from the line.
- **Block features** gain `glass`, a box drawn as glass and never in masonry.
  A feature's `base_m` may be negative, so a column can reach ground that
  steps down below its block's ground (the north deck's entrance hall).
- **Corner numbering:** survey sightings name OSM corners by index
  (`8421#2`). Cutting a block out of a footprint keeps the numbers of the
  corners it leaves alone: the ring is turned to start like the parent's.
  Renumbering once moved the north deck's poses 3-6 m.
- **Doors whose label names no block** (`scene_overrides.toml [blocks]`):
  the block is set by hand, from the sign seen on the panorama and the tour's
  links; the rooms reached through the door inherit it.

## Consequences

- Every fact on the map has a source a reviewer can check: a sighting, a
  URL, a crop.
- Assets are optional for readers: a missing `pois.json` or
  `furniture.json` means none, so web and API deploys never wait on data.
- The notebooks need upkeep when the campus changes. The verification date
  on each POI says how fresh it is.
