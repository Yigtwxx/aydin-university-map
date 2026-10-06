# ADR-0008: Dense textured campus mesh with OpenMVS, tiled for the web

- Status: accepted
- Date: 2026-10-06

## Context

The sparse models of `outdoor96_lg` are georeferenced (ADR-0005, ADR-0006), but
the web app still extrudes OSM footprints with guessed heights. A textured
mesh of the reconstructed campus core is needed. The constraints are the same
as before: an Apple Silicon Mac, no CUDA, no training. COLMAP's
`patch_match_stereo` needs CUDA. Cloudflare Pages accepts files up to 25 MiB.

The input is unusual for MVS. Each panorama is a rig of five 1300 px cube faces
(90° each, the up face is not used), the panoramas are about 6 m apart, and the
down face shows the patched nadir and the tripod or vehicle.

## Decision

1. **OpenMVS 2.4.0, official macOS arm64 release**, called as external
   processes from `$OPENMVS_BIN` (ADR-0002). The binaries link only system
   frameworks, so no Homebrew libraries are needed. **gltfpack 1.3** (native
   meshoptimizer release, MIT) comes from `$GLTFPACK_BIN`.
2. **`amap dense run`** (`pipeline/src/amap_pipeline/recon/dense.py`) runs
   resumable stages. Each tool call has its own log, an overall timeout and
   a stall watchdog (no log output and no CPU for 30 min):
   - the sparse model without the nadir (`d`) faces, faces with fewer than
     10 sparse points and points closer than 0.3 m to a camera (the last two
     crash DensifyPointCloud);
   - `colmap image_undistorter` (a copy, since the faces are pinhole);
   - `InterfaceCOLMAP`;
   - `DensifyPointCloud` at full resolution with all neighbour views. ROI
     estimation, ROI cropping and tower mode are off, because those modes are
     for object and aerial captures;
   - `ReconstructMesh`;
   - a clean step that drops faces more than 1 m from every dense point (sky
     blobs and hull surfaces made up by the graph cut) and islands under 200
     faces;
   - `RefineMesh` with auto decimation, followed by the same clean test,
     because refinement grows spikes on this data;
   - a quadtree of tiles;
   - per tile, `TextureMesh` to a GLB, then the georeference baked into the
     vertices, then `gltfpack -cc -tc` (meshopt geometry, KTX2/ETC1S
     textures);
   - `data/out/mesh/index.json`.
3. **Tiles are cut before texturing.** Each tile is textured on its own and
   carries only its own atlas. Splitting a textured mesh would copy the whole
   atlas into every tile. A packed tile over 25 MiB is split into its
   quadrants and textured again. A tile that is already as small as allowed
   gets its textures halved instead.
4. **Output frame:** three.js world metres, `(x, y, z) = (east, up, -north)`.
   This is the mapping of `enuToWorld` in the web app, with the same origin
   as every other asset. The web app loads the tiles without a transform.
5. **Seam levelling is off** (`--global-seam-leveling 0
   --local-seam-leveling 0`). In this build, global levelling fills every
   texture patch with black and local levelling paints thick black or
   coloured borders. This was checked on the same tile with each option
   alone. Without levelling the atlas is correct, but exposure seams between
   panoramas stay visible.
6. **Texturing uses `scene.mvs`, not `scene_dense.mvs`.** The latter stores
   the images at the densify resolution (650 px), which would halve the
   texture detail.
7. **Building heights** (`amap dense heights`, `geo/sfm_heights.py`):
   - ground = p10 of the points 3–10 m outside the footprint, using
     horizontal surfaces within ±4 m of the model ground only (glass
     mirrors produce "ground" tens of metres below it) and leaving out other
     footprints;
   - roof = p95 of the points inside the footprint shrunk by 1 m, counting
     only points more than 1 m above the ground;
   - a height is kept with at least 30 points inside and 3–80 m;
   - in `amap export buildings` a kept height only raises a lower
     `height_m` (`height_source = "sfm"`), because it is a lower bound.
8. **The meshes are not shipped in the web app.** The map's photoreal view
   uses Google Photorealistic 3D Tiles (Cesium ion), which cover every
   building, roof and the surroundings. The SfM tiles cover four partial
   areas with holes and exposure seams, so they would look worse than both
   the styled massing and the Google tiles. They stay a pipeline output for
   heights, inspection and later work.

## Results (2026-10-06)

- Model 0 densifies to 1.08M points in 26 min. Its tile has 101k faces
  (4.0 MiB with an 8k atlas).
- Models 1, 2 and 4 take 6 min, 31 s and 10 s.
- Every model fits in one tile.
- Facades align with OSM outlines for model 1 (82% of facade points within
  2 m) and only partly for model 0 (52%).
- Three building heights were measured: A 11.1 m, B 7.1 m, D 6.0 m. All are
  below the style defaults (14.2, 17.6, 17.6 m), so none is applied.
- Metric scale check: two cues in the dense cloud (camera height above
  nearby horizontal surfaces, window-row spacing) hinted at a scale about
  2× too small. The georeference contradicts this. The tripod height
  `-ground_z_model × scale` is 1.83 m (model 0), 1.74 m (1), 1.66 m (2)
  and 1.46 m (4), and model 1's facades sit on the OSM outlines. The
  scale is kept. The low measured heights are explained by the missing
  upper floors (see Consequences). Timings and quality per tile are in
  `docs/reconstruction.md`.

## Alternatives considered

- **COLMAP `patch_match_stereo`:** CUDA only.
- **COLMAP `delaunay_mesher` on the sparse points:** 26k points for model 0
  give a blob mesh with no usable facades.
- **Open3D TSDF fusion:** needs depth maps first, which brings back the MVS
  problem.
- **`brew install openmvs`:** not needed, because the official release runs
  as it is.
- **Learned MVS (MVSNet and similar):** needs a GPU for useful resolutions.
  The project rule also excludes training.
- **Texturing the whole mesh and splitting it afterwards:** every tile would
  carry the full 8k atlas.
- **RefineMesh without decimation (`--decimate 1`), or at full
  resolution:** both diverge into spikes several metres long.
- **No refinement:** clean, but 4–10× more triangles. It stays available
  as `--no-refine`.

## Consequences

- AGPL covers only the OpenMVS binaries. They are never vendored, linked or
  shipped. The meshes are our derived data. The AGPL does not cover them;
  they fall under the data policy (gitignored, published to Pages only).
- The web app needs `KTX2Loader` (Basis transcoder) and `MeshoptDecoder` to
  load the tiles. They are unlit (`KHR_materials_unlit`) and double-sided.
- Coverage is limited by street-level capture:
  - facades up to roughly the first floors and the paved courtyards are
    reconstructed;
  - roofs, upper floors and anything not seen from the walk are not.
- SfM heights are usually lower bounds, because upper floors are rarely
  reconstructed. They also depend on the model's metric scale and its
  alignment to OSM. `index.json` stores coverage and hole ratios per tile.
  `dense_report.json` stores stage timings and clean-up counts.
- Exposure seams between panoramas stay visible until a working seam
  levelling is available (a newer OpenMVS build or our own colour
  balancing).
