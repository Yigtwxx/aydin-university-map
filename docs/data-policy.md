# Data policy

This repository is public and MIT-licensed. **The data it processes is not.**

## Tour data (copyrighted — never committed)

The 3D model and walking graph are derived from the official İstanbul Aydın
University 360° virtual tour (`360.aydin.edu.tr`). Panoramas, tiles, tour
metadata dumps and everything derived from them (point clouds, meshes, textures,
pano poses, generated descriptions) belong to the university and the tour vendor.
The project uses them with permission obtained by the maintainer. In the app
they are credited as "360° görüntüler: İstanbul Aydın Üniversitesi sanal turu".

Rules:

1. Everything under `data/` is gitignored and must never be committed.
2. No panoramas, tiles, crops, screenshots of panoramas, meshes or point clouds in
   issues, pull requests, docs or test fixtures. Tests use **synthetic** fixtures only.
3. Generated assets are published to Cloudflare Pages (see
   [ADR-0004](adr/0004-free-hosting-without-domain.md)) and served to the web app
   from there, never from git. The maintainer confirmed public display is allowed.
4. `tools/repo_guard.py` enforces rules 1–2 in pre-commit and CI; gitleaks scans
   for secrets.

If you only want to run the code, you need your own authorised copy of the data.

## OpenStreetMap

Building footprints and footways come from OpenStreetMap via Overpass/osmnx.
© OpenStreetMap contributors, available under the
[Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).
Derived databases that mix OSM data stay under ODbL share-alike terms; the web app
shows the attribution.

## Weather

Live weather comes from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0, free API
for non-commercial use). The attribution is shown in the app footer.

## Third-party tools

- **OpenMVS** (AGPL-3.0) is used only as an external command-line binary in the
  offline pipeline. It is never vendored, linked or distributed with this
  repository, so the MIT licence of this code is unaffected (see
  [ADR-0002](adr/0002-openmvs-as-external-tool.md)).
- **COLMAP / pycolmap** (BSD-3-Clause) is a regular Python dependency.

## AI services

The assistant uses free tiers of Groq and Google Gemini. Prompts on Gemini's free
tier may be used by Google to improve its products, so the app must never send
personal data and shows a notice to users.
