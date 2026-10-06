# ADR-0009: Indoor routing from the tour's own links

- Status: accepted
- Date: 2026-10-06 (revised 2026-10-07 after review)

## Context

Outdoor routing stands on SfM poses. Indoors there are none: corridors and
rooms repeat, glass and blank walls defeat feature matching, and no indoor
model was reconstructed. The tour still says a lot: which panorama links to
which (entrance -> corridor -> room), the labels name blocks and floors
("M Blok -1.Kat", "FTR - M Blok 2.K"), and each hotspot sits where the doorway
is in the picture (krpano `ath`, within ~6° of SfM bearings outdoors, 80 %
within 20°). There are no stairs or elevator labels.

## Decision

Indoor panoramas, and entrances SfM could not pose, hang off the measured
network through tour links (`pipeline/src/amap_pipeline/graph/indoor.py`):

- **Position**: none of their own. A node stands at the measured node it
  hangs off (`Node.anchor`, `pose_source = interpolated`), so every straight
  line between two nodes is still a lower bound of the walk and A*'s
  heuristic stays admissible. Clients draw only measured nodes. A node
  linked from several spots hangs off one in its own block, then in its own
  tour area ("Tıp Fakültesi Hastanesi Giriş" off "Acil Giriş"), then a door.
- **Floor**: from the label first, then the area. "Bodrum"/"B" is a
  basement and a plain "3.Kat" the third floor. A hyphen right before the
  digit ("T Blok -2.Kat", "M Blok -5 Koridor") is a basement by default, and
  certainly one when the building writes the same floor plainly elsewhere
  ("Kütüphane 1.Kat"). A hyphen glued to a word ("M Blok-5.K") is a minus
  sign or a separator: it follows the linked spots (ties: upper floor). A
  default flips only when it would jump three floors or more to a linked
  spot of certain floor and the other sign jumps less in total. Else the
  floor is carried over from linked spots on one known floor. Entrances are
  at ground level unless labelled. A label that writes its floor with the
  other sign is never shown next to a floor badge.
- **Edges within one position** (a room and its door): 12 m estimates
  (`length_source = estimate`). **Stairs** wherever the storey changes, +15 s
  per floor; spots of unknown floor count as halfway between the known
  floors around them, so a change of floor through them is stairs too and
  every step-free stretch stays on one known floor (checked at export).
- **Edges between two positions**: two doors (or a door and an open area)
  take the outdoor rules (60 m at most, round buildings with clearance) and
  become a walk outside; otherwise, and always when a room is at one end,
  the link is a **passage** through a building (`Edge.passage`). A link
  between two rooms four or more known floors apart is a menu jump of the
  tour: a passage that keeps its stairs cost and always pays the penalty.
  Passages are never drawn and are the only lines exempt from the footprint check
  besides links within one position.
- **Islands** of the measured network join the main one by the shortest
  reasonable walk outside (120 m at most): the T Blok garden, cut off
  before, now walks 93 m round one building to Acil Giriş.
- **Hotspot yaws** (`Edge.source_yaw_deg`, `target_yaw_deg`) let the 360°
  walk face the next doorway where positions cannot.

The API keeps the outdoor step builder for measured stretches and describes
indoor ones by action (enter, continue to, stairs up/down, walk through,
leave, arrive). A passage costs 60 s on top of its walk unless it lies in the
indoor network of a room the route starts or ends in, so outdoor routes cut
through a building only as a last resort. Routes with estimated parts say so
(`approximate`) and list the runs the map can draw (`parts`). Rooms are
places grouped by label, block and floor.

## Consequences

- 339 indoor nodes (17 of them doors), 493 indoor edges: 62 stairs, 68
  passages (1 of them the menu jump T Blok 3.Kat to the library's -3),
  1 door-to-door walk outside; 1 island bridge. 87 nodes are on basement
  floors; the other jumps above two floors are entrance halls linked to
  their floors' corridors.
- Over all 48,620 place-to-place routes: no drawn line crosses a footprint,
  no route passes through a building it neither starts nor ends in, and no
  step-free route changes floor. 29,834 pairs have no step-free route: the
  tour has no lift data, and a wrong "step-free" is worse than none.
- Every new field is optional, so graphs and APIs of either age read each
  other; a newer API adds turn values, which the web shows from the API's own
  text when it does not know them. Deploy API and web before the graph.
