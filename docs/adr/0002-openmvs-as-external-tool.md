# ADR-0002: Use OpenMVS only as an external tool

- Status: accepted
- Date: 2026-10-06

## Context

Dense reconstruction must run on an Apple Silicon Mac without CUDA and without
training any model. COLMAP's patch-match stereo requires CUDA/HIP. OpenMVS 2.4.0
ships official macOS arm64 binaries that run on CPU (`--gpu-device -2`) and export
textured GLB meshes. OpenMVS is licensed AGPL-3.0; this repository is MIT.

## Decision

The pipeline calls the OpenMVS binaries (`InterfaceCOLMAP`, `DensifyPointCloud`,
`ReconstructMesh`, `RefineMesh`, `TextureMesh`) as separate processes, located via
the `OPENMVS_BIN` environment variable. OpenMVS is never vendored, linked,
imported or redistributed here, and the web/API services never run it.

## Consequences

- The MIT licence of this code is unaffected; generated meshes are not covered by
  the AGPL.
- Contributors install OpenMVS themselves (setup guide: `docs/reconstruction.md`, added with the reconstruction phase).
- If OpenMVS is impractical, fallbacks are COLMAP's CPU `delaunay_mesher` +
  `mesh_texturer` or Open3D TSDF fusion.
