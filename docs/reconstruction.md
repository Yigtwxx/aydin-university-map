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
