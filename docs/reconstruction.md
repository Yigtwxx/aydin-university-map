# Reconstruction pipeline

How to go from the authorised tour data to a sparse reconstruction. All outputs
stay under `data/` (gitignored); see the [data policy](data-policy.md).

## Requirements

- macOS on Apple Silicon (or Linux), Python 3.12 via uv
- `uv sync --all-packages --all-extras` (installs pycolmap 4.2.x, CPU)
- An authorised tour metadata dump in `data/raw/tour_scenes.json`
- Phase 2 (dense meshes): OpenMVS 2.4.0 binaries, path in `OPENMVS_BIN`
  (external tool only, see [ADR-0002](adr/0002-openmvs-as-external-tool.md))

## Steps

```bash
# 1. Classify Florya scenes and pick a connected scene set
uv run amap tour build
uv run amap tour select --hub scene_428523 --n 35 --name spike35

# 2. Receive cube faces from the authorised browser session (loopback only)
uv run amap tiles serve            # prints a session token
uv run amap tiles verify --set spike35

# 3. Gate G1: verify the cube-face orientation and write the rig config
uv run amap rig seam-test --set spike35

# 4. Sparse SfM and evaluation (gates G2-G5)
uv run amap sfm run --config pipeline/configs/spike.toml
uv run amap sfm report --run spike35_v1   # writes evaluation.json + top-down PNG
```

## Conventions

- Cube faces follow krpano: `f` front, `r` right, `b` back, `l` left, `u` up
  (bottom edge touches front), `d` down (top edge touches front).
- Each face is a 90° pinhole camera: `SIMPLE_PINHOLE f = cx = cy = W/2`.
  Faces smaller than 1300 px (some scenes use 966 px) are resized during staging.
- The rig frame is the front camera; gravity is the rig's +y axis.

Results and design consequences of the first run: [ADR-0003](adr/0003-sfm-spike.md).

## Dense mesh (Phase 2)

Textured, tiled meshes of the georeferenced models for the web app. The
decision record is [ADR-0008](adr/0008-dense-mesh-openmvs.md).

### Tools

External binaries, never committed (ADR-0002). Install each in its own
directory and record the paths in `.env`:

| Tool | Source | `.env` |
|---|---|---|
| OpenMVS 2.4.0 | GitHub `cdcseacave/openMVS`, asset `OpenMVS_macOS_arm64.zip` (arm64 Mach-O, statically linked, only system frameworks) | `OPENMVS_BIN=<dir with DensifyPointCloud ...>` |
| gltfpack 1.3 | GitHub `zeux/meshoptimizer`, asset `gltfpack-macos.zip` | `GLTFPACK_BIN=<path to gltfpack>` |
| COLMAP CLI | `brew install colmap` (4.2.1) | `COLMAP_BIN` (optional, default `colmap`) |

Licences:
- OpenMVS is AGPL-3.0. It runs only as a separate process, so it does not
  affect the MIT licence of this code.
- gltfpack is MIT.
- The meshes are our derived data. The AGPL does not cover them, but the
  [data policy](data-policy.md) does: they are gitignored and published to
  Pages only.

### Run

```bash
uv run amap dense run --run outdoor96_lg --model 0 --resolution-level 0 --number-views 0
uv run amap dense run --run outdoor96_lg --model 4 --resolution-level 0 --number-views 0 --no-refine
uv run amap dense heights --run outdoor96_lg --model 0 --model 1 --model 2 --model 4
uv run amap export buildings      # applies data/derived/sfm_heights.json
```

Long runs go in the background under `caffeinate -dimsu` with a log in
`data/logs/`. Each stage writes one file in `data/recon/<run>/dense_m<N>/`
and is skipped when that file exists:
- `--redo-from <stage>` redoes that stage and everything after it;
- `--until <stage>` stops after that stage;
- `--force` redoes every stage.

Each tool logs to `dense_m<N>/logs/<stage>.log`. A tool is killed after
`--timeout-h` (default 3 h), or after 30 min with neither log output nor CPU
use. Stage timings and counts go to `dense_m<N>/dense_report.json`.

Everything up to `refine` works in model coordinates. After a new
georeference, `--redo-from tiles` is enough: about a minute instead of half
an hour.

| Stage | What it does |
|---|---|
| `filter` | sparse model as TXT with three removals: the nadir (`d`) faces, which show the patched nadir and the tripod or vehicle; faces with < 10 sparse points (no depth range: DensifyPointCloud aborts with a bogus exabyte allocation); sparse points < 0.3 m from a camera |
| `undistort` | `colmap image_undistorter`. The faces are pinhole, so this is a copy. The output folder is wiped first, because the tool aborts on existing files. |
| `interface` | `InterfaceCOLMAP` → `scene.mvs` |
| `densify` | `DensifyPointCloud` with `--estimate-roi 0 --crop-to-roi 0 --tower-mode 0` (those modes target object and aerial scenes). Depth maps are deleted before and after. |
| `mesh` | `ReconstructMesh` |
| `clean` | drops faces whose centroid is more than 1 m from every dense point (sky blobs and hull surfaces made up by the graph cut), then islands under 200 faces |
| `refine` | `RefineMesh` on `scene.mvs` (`--refine-resolution-level`, default 2; auto decimation) |
| `tiles` | runs the clean test again on the refined mesh (RefineMesh grows spikes, see below), crops to the cameras' bounding box + 120 m (and z −15…100 m) in ENU, then builds a quadtree with ≤ 400k faces per tile (tile meshes stay in model coordinates) |
| `pack` | per tile: `TextureMesh` on `scene.mvs` (full 1300 px images, seam levelling off) → GLB with the atlas embedded, similarity baked into the vertices, `gltfpack -cc -tc`. A tile over 25 MiB is split into its quadrants and textured again. |

`--resolution-level` is relative to the 1300 px faces. OpenMVS never goes
below `--min-resolution 640`, so levels 1 and 2 both densify at 650 px.

### Measured (`outdoor96_lg`, 2026-10-06, M4 Pro 14 cores, CPU only)

Densify settings compared on model 0 (192 faces):

| Densify settings | Points | Time |
|---|---|---|
| level 2 (650 px) | 281k | 3.1 min |
| level 1 + `--number-views 8 --postprocess-dmaps 7 -t 0.02` | 184k | 7.2 min |
| level 1 + `--fusion-depth-diff-threshold 0.03` | 310k | 5.6 min |
| level 1 + `--number-views 0` | 323k | 8.5 min |
| level 0 (1300 px) | 929k | 16.8 min |
| **level 0 + `--number-views 0` (used)** | **1.08M** | **25.7 min** |

Final runs (seconds). The models ran partly in parallel, so the times
overlap:

| Model | Faces used | Densify | Mesh | Refine | Pack | Mesh faces → tile | GLB |
|---|---|---|---|---|---|---|---|
| 0 (48 panos) | 192 | 1541 | 31 | 62 | 55 | 1.03M → 101k | 4.0 MiB, 8k atlas |
| 1 (15) | 60 | 385 | 27 | 11 | 9 | 389k → 39k | 2.4 MiB, 4k atlas |
| 2 (9) | 21 | 31 | 0.1 | 3 | 2 | 6.4k → 1.7k | 0.3 MiB |
| 4 (6) | 24 | 10 | 0.2 | — | 1 | 3.7k | 0.1 MiB |

Every model fits in one tile, far below 25 MiB.

Quality (`index.json`):
- **coverage share:** 18% (model 0) and 11% (model 1);
- **hole ratio:** 0.8–2.9% open edges;
- **untextured area:** 4% for models 0 and 1, 14% for model 2, 50% for
  model 4.

Facade points of the dense cloud lie within 2 m of an OSM outline for 82%
of model 1 and 52% of model 0. Model 0's northern facades sit on their
outlines, but its southern and eastern parts are 5–25 m off.

### Findings

- **Seam levelling is off.** In the 2.4.0 macOS build, global levelling
  fills every texture patch with black and local levelling paints thick
  borders. Without it, exposure seams between panoramas stay visible.
- **RefineMesh is unstable on this data.**
  - Auto decimation reduces the mesh to about 10%, and the refined mesh
    grows spikes several metres long.
  - `--decimate 1` (no decimation) and `--resolution-level 0` make the
    spikes much worse.
  - The clean test after refinement removes them.
  - `--no-refine` keeps the 0.4–1M-face Delaunay mesh. It is cleaner but
    heavier.
- **RefineMesh hangs** at 0% CPU on a mesh of a few hundred faces
  (model 4). The stall watchdog catches this; model 4 runs with
  `--no-refine`.
- **Model 2** aborted in DensifyPointCloud until faces without sparse
  points and points at the camera centre were filtered out.
- **The ground is thin.** Most of the cloud is facades: only 2.4% of the
  points have horizontal normals. Paved courtyards come out patchy at
  full resolution.
- **Metric scale (checked).** Two cues in the dense cloud hinted at a
  scale about 2× too small: the cameras sit only about 0.7 m (median)
  above the horizontal surfaces next to them, and window rows on several
  facades are about 1.4 m apart. The georeference disagrees. The tripod
  height `−ground_z_model × scale` is 1.83 / 1.74 / 1.66 / 1.46 m for
  models 0 / 1 / 2 / 4, and model 1's facades sit on the OSM outlines. The
  likely explanations are raised surfaces near the cameras (kerbs,
  planters, steps) and transoms counted as window rows. The scale is kept.

### Outputs

- `data/out/mesh/<run>_m<N>/<tile>.glb`: meshopt geometry with KTX2
  (ETC1S) textures, unlit and double-sided. Tile names are quadtree paths
  (`r`, `r0` … `r3`, `r01` …). The web app needs `KTX2Loader` and
  `MeshoptDecoder`.
- Frame: three.js world metres, `(x, y, z) = (east, up, −north)`. This is
  `enuToWorld` with the campus ENU origin. `y = 0` is the local ground under
  the model's cameras (camera height − 1.6 m).
- `data/out/mesh/index.json` has one entry per run and model (georef method
  and ICP RMS, resolution level) and, per tile:
  - `file`, `bytes`, `bounds.min/max` (world), `triangles`, `texture_px`;
  - `quality.coverage_share`: share of the 2 m cells within 30 m of a camera
    that hold geometry;
  - `quality.hole_ratio`: open edges of the cropped mesh divided by face
    edges (tile cuts do not count);
  - `quality.untextured_share`: area share of faces no image saw
    (TextureMesh's orange empty colour).
- `data/derived/sfm_heights.json`: `{osm_id: {height_m, points, ground_m}}`.
  `amap export buildings` uses a height only when it is above the current
  estimate (it is a lower bound) and then sets `height_source = "sfm"`.
- Heights (`geo/sfm_heights.py`):
  - ground = p10 of the horizontal-surface points 3–10 m outside the
    footprint, within ±4 m of the model ground and outside other
    footprints;
  - roof = p95 of the points inside the footprint shrunk by 1 m, counting
    only points > 1 m above the ground;
  - a height is kept with ≥ 30 points inside and 3–80 m.

  On 2026-10-06 three heights were measured. All are lower than the style
  defaults, so none is applied:

  | Building | SfM height | Default before |
  |---|---|---|
  | A | 11.1 m | 14.2 m (4 levels) |
  | B | 7.1 m | 17.6 m (5 levels) |
  | D | 6.0 m | 17.6 m (5 levels) |

  Street-level capture rarely reaches the roof line, and the up faces are
  not used, so upper floors are missing. These heights are lower bounds.
- The tiles are not shipped in the web app (ADR-0008): its photoreal view
  uses Google Photorealistic 3D Tiles.
