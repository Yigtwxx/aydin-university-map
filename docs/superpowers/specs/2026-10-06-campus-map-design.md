# Aydın University Map — 3D campus from the 360 tour + shortest walking paths (Florya)

> Approved design (2026-10-06). Living document: later changes are recorded as ADRs in `docs/adr/`.
> Updates: hosting moved from R2 to Cloudflare Pages ([ADR-0004](../../adr/0004-free-hosting-without-domain.md)); app name "Aydın Campus Map", independent branding, desktop-first UI; spike results in [ADR-0003](../../adr/0003-sfm-spike.md).

## Context

**Main task (user, repeated):** "Aydın Üniversitesinin 360 mapinden 3D mapini çıkartıp en kısa yürüyüş yollarını maplememiz gerekiyor."
The only data source is the krpano tour at `360.aydin.edu.tr` (used with permission obtained by the maintainer; no original/raw files are available). We reconstruct a **metric, georeferenced 3D model of the Florya campus from the tour panoramas**, derive a **metric walking graph**, compute **shortest walking routes**, and ship a premium Next.js app (3D map, animated route, step-by-step 360° walkthrough, live sun/weather, AI assistant, scroll-driven fly-in landing). Critical path: **tiles → SfM → georeference → metric graph → A\* → web**. Everything else is secondary.

## Fixed decisions

- Florya only. MVP = outdoor (building ↔ building + entrances); indoor + photo localization later.
- FastAPI (Python 3.12, uv) + Next.js 16 (TS strict, pnpm). Supabase (PostGIS + pgvector), no separate vector DB.
- LLM: free APIs — **Groq `openai/gpt-oss-120b` primary, `gemini-3.5-flash-lite` fallback + vision** (swapped after quota research). `pydantic-ai` FallbackModel.
- **Everything runs on the Mac (M4 Pro, 14 cores, 48 GB, 142 GB free).** **No model training / per-scene optimization** (no 3DGS/NeRF) → classical photogrammetry; pretrained-model **inference** allowed only as fallback.
- 3D view: stylized massing (default) + photoreal textured mesh toggle; optional Google 3D Tiles layer later (Phase 7, behind flag).
- Live sun & weather: live default + time slider/weather override; 360 at night = subtle grade (≤ 25%).
- MIT, public repo `Yigtwxx/aydin-university-map` (gh logged in, repo not yet created). Raw/derived imagery **never** in git → Cloudflare R2. Web: Vercel; API: Render free.

## Data findings (already extracted → `data/raw/`, gitignored)

- 576 scenes, **424 Florya** (2 components: 418 + 6). 700 undirected nav links (`linkedscene`, `ath`, `bakacakyon`), 0 dangling.
- `hedefibelirle(...)` params: `[0]` id, `[1]` n links, `[2:8]` ath, `[8:14]` linked ids, `[14:20]` sector mids, `[20:26]` arrival heading, `[26:28]` lat/lng, `[28]` p28 (maybe pano compass heading — validate against SfM), `[29:31]` place group, `[31:35]` labels TR/area TR/area EN/label EN.
- Labels give building/floor/room (T Blok -1..4, Kütüphane -3..3, Öğrenci İşleri…). Outdoor via `labels[0]` keywords = 100 scenes, **one connected component**, 56 link to entrances (A/B/D/E/F/G-H/J/M/O/T, Kütüphane, Hastane, Technocenter, Gastronomi, Yurt…); all-label match = 124 → needs a manual override list. BFS from `scene_428523` "Kampüs": first 35 = 28 "Kampüs" + 7 entrances → **spike set**.
- Coords coarse (one per building/area) → anchors only. Hotspot angles inconsistent (28% within 15°) → poses from images.
- Tiles: `panos/<id>.tiles/pano_{f,b,l,r,u,d}.jpg` 1300² (~2.4 MB/pano, ~1 GB Florya). Exported from an authorised browser session into a local 127.0.0.1 sink.

## Architecture

```
tour (browser)      ──► sink ──► data/tiles/<scene>/<face>.jpg
   │                                   │
   └─ scene meta ─► amap tour build    ▼
                                 rig seam test ─► pycolmap SfM (cubemap rig, tour-graph pairs)
                                       ▼
                     georef: gravity + tripod-height scale + OSM footprint ICP (EPSG:32635)
                        ▼                         ▼                           ▼
              OpenMVS dense/mesh/texture   massing (OSM + point heights)   graph.geojson + pois.json
                 ▼ gltf-transform                ▼                          ▼
               R2 (GLB, KTX2)            buildings.geojson          Supabase (PostGIS/pgvector)
                        └──────────────► Next.js (R3F, PSV) ◄── FastAPI (A*, POI, weather, chat SSE)
```

```
aydin-university-map/
  apps/web/              Next.js 16 (src/app/[locale], features/*)
  apps/api/              uv member amap-api (src/amap_api)
  pipeline/              uv member amap-pipeline (src/amap_pipeline), Typer CLI `amap`
  packages/contracts/    uv member amap-contracts: pydantic models (graph, pois, buildings), normalize_tr(),
                         ENU origin, JSON Schema export, synthetic fixtures
  supabase/              config.toml, migrations/, seed.sql (synthetic only)
  tools/browser/         fetch-tiles.js (no data)
  docs/                  architecture.md, data-policy.md, reconstruction.md, adr/
  data/                  GITIGNORED: raw/ tiles/ derived/ recon/ osm/ georef/ out/ rag/ debug/
  .github/               workflows/ (ci, e2e, keepalive, rag-eval), ISSUE_TEMPLATE/, PR template, dependabot.yml
  pyproject.toml         [tool.uv.workspace]; pipeline extras: recon (pycolmap[panorama], open3d), geo (osmnx, shapely, pyproj), rag
  package.json, pnpm-workspace.yaml, .python-version (3.12), .nvmrc (24), .pre-commit-config.yaml, .env.example
```

Contracts are the single source of truth: pydantic (`amap_contracts`) → FastAPI OpenAPI (`apps/api/openapi.json`, committed) → `openapi-typescript` → `apps/web/src/lib/api/schema.d.ts`; pipeline output validated against exported JSON Schemas. CI fails on drift.

## Phases

### Phase 0 — Bootstrap + public repo
1. `git init`; write `.gitignore` **first** (`data/`, `.env*` except `.env.example`, `.venv`, `node_modules`, `*.glb/*.ply/*.bin` outside fixtures, COLMAP/OpenMVS workspaces); verify `git status` shows no data.
2. Root configs (uv + pnpm workspaces, ruff, pyright, prettier, eslint 9 flat, pre-commit with data guard), LICENSE (MIT 2026), README (TR+EN), CODE_OF_CONDUCT (Contributor Covenant 2.1), CONTRIBUTING, SECURITY, issue forms + PR template ("no raw data" checkbox), dependabot (groups: three/R3F/PSV), `docs/data-policy.md` (tour copyright, never-commit rule, OSM ODbL, Open-Meteo CC BY 4.0, OpenMVS AGPL external-only).
3. Port `data/raw/analyze_tour.py` → `pipeline/src/amap_pipeline/tour/{parse,classify,select}.py` (typed, synthetic 12-scene fixture tests).
4. CI `ci.yml`: web (lint, prettier --check, `tsc --noEmit`, vitest, `next build`), python matrix (ruff check + format --check, pyright, `pytest -m "not db and not recon"`), contracts drift, db (supabase CLI + migrations), guard (gitleaks, no `data/`, no file > 1 MB, no JPG/GLB/PLY outside fixtures).
5. First commit `chore: bootstrap monorepo` → `gh repo create aydin-university-map --public --source . --push`; topics; secret scanning + private vulnerability reporting.
- **Accept:** CI green, `git ls-files | grep -c '^data/'` = 0, community files present.

### Phase 1 — Critical spike: tiles + rig + SfM on 35 outdoor panos
1. `amap tour build` → `data/derived/scenes.json`; `amap tour select --hub scene_428523 --n 35` → `sets/spike35.txt`; kinds outdoor/entrance/indoor via keywords + `scene_overrides.yaml`.
2. **Tile sink** `acquire/sink.py` (`amap tiles serve`): stdlib `ThreadingHTTPServer` on 127.0.0.1, random session token header, CORS origin exactly `https://360.aydin.edu.tr` + `Access-Control-Allow-Private-Network`, `GET /queue?set=` (resumable), `POST /tile/{scene}/{face}` raw JPEG + `X-SHA256` → verify hash, JPEG markers, Pillow 1300×1300 → atomic write + `manifest.jsonl`; `amap tiles verify`.
3. **Browser script** `tools/browser/fetch-tiles.js`: read each scene's cube URL from krpano runtime, 3 parallel fetches, 200–500 ms jitter, SHA-256, retry ×3, pause 60 s on 403/429. Volumes: spike ~210 files (~85 MB), outdoor 600, Florya ~2,544 (~1 GB).
4. **Rig seam test** `recon/cubemap.py` (`amap rig seam-test`): score edge continuity for candidate face orientations → verified `data/recon/rig_config.json`. Start values: SIMPLE_PINHOLE `650,650,650`; `cam_from_rig_rotation` [w,x,y,z] f ref, r `[0.70711,0,-0.70711,0]`, b `[0,0,1,0]`, l `[0.70711,0,0.70711,0]`, u `[0.70711,-0.70711,0,0]`, d `[0.70711,0.70711,0,0]`. Unit test: synthetic equirect → cube → seam error ≈ 0.
5. **Masks + pairs** `recon/{masks,pairs}.py`: tripod/logo disc on d; drop u outdoors; pairs = 1-hop (opt. 2-hop) tour links × 5×5 faces → `pairs.txt`.
6. **SfM** `recon/sfm.py` (`amap sfm --config pipeline/configs/spike.yaml`), pycolmap 4.2.1: `extract_features(PER_FOLDER, mask_path)` → `apply_rig_config` → `match_image_pairs(ImportedPairingOptions, rig_verification, skip_image_pairs_in_same_frame)` → `incremental_mapping(ba_refine_sensor_from_rig=False, no intrinsics refine)` → `report.json`.
7. **Evaluate** `recon/evaluate.py` (`amap sfm report`): gravity from rig down-axis, scale = 1.6 m / median camera-to-ground (d-face points), quick 2D sim fit to anchors, trajectory GeoJSON + Leaflet overlay on OSM (`data/debug/`), SfM heading vs p28.
- **Go/no-go (all):** G1 one consistent face orientation; G2 ≥ 32/35 panos registered (all faces) in one model; G3 mean reproj ≤ 1.5 px, median track ≥ 3; G4 camera-height CV ≤ 15%, tour edge median 3–25 m, entrances ≤ 5 m (max 10) from footprint after fit, ≤ 2 footprint crossings; G5 ≤ 2 h runtime.
- **Fallback ladder** (each 0.5–1 day): `global_mapping` → stronger SIFT (16k, affine, DSP) → ALIKED+LightGlue (pycolmap ONNX/CoreML, inference) → 2–3 hop + vocab-tree pairs → split/merge clusters by Sim3 on shared frames + pose graph over tour links with gravity/OSM priors → direction-only rotation/translation averaging constrained by OSM (+ p28 prior if validated) → last resort: snap tour nodes to OSM footways, OSM edge lengths (routes still ship).
- Record outcome in `docs/adr/0003-sfm-spike.md`; measured runtimes replace estimates.

### Phase 2 — Full reconstruction, georeference, models, graph export
1. Outdoor 100 (one component) while 424 Florya tiles download in background; indoor per building/place group, each including its entrance panos + outdoor neighbours → Sim3-anchored via shared frames.
2. **Georeference** `geo/{osm,align}.py` (`amap georef`): osmnx footprints/footways cached in `data/osm/`; 4-DoF gravity; tripod scale; 2–3 manual control points (`data/georef/control_points.yaml`) → Open3D 2D ICP (`with_scaling=True`) of wall points 0.5–3 m vs sampled footprint edges in EPSG:32635 → `Reconstruction.transform`, `sim3.json`. **Accept:** median entrance-to-footprint ≤ 3 m (max 6), ICP RMS ≤ 1.5 m.
3. **Dense** `recon/dense.py` (`amap dense --building A`): crop to panos ≤ ~40 m of façade → `undistort_images` → OpenMVS 2.4.0 arm64 (`OPENMVS_BIN`, `--gpu-device -2`, `--tower-mode 0 --estimate-roi 0 --crop-to-roi 0`) Densify → ReconstructMesh → RefineMesh → `TextureMesh --export-type glb` → `gltf-transform optimize --compress meshopt --texture-compress ktx2 --texture-size 2048`; per-building quality flag decides shipping (5–15 MB per building). Option: `--resolution-level 1` (~3–4× faster).
4. **Massing** `geo/massing.py`: height = p95 point z in footprint − ground (camera z − 1.6 m); fallback OSM `building:levels × 3.2` / Overture; `pipeline/configs/buildings.yaml` (codes, names, OSM way ids, committed) → `buildings.geojson`.
5. **Graph + POIs** `graph/{build,pois}.py` (`amap graph export`), schema in `amap_contracts.graph`:
   - `graph.geojson` meta `{version, generated_at, run_id, origin:[28.7971,40.9915], crs}`; **Node** (PointZ): `id, kind(outdoor|entrance|indoor), building, floor, enu[x,y,z], heading_deg, tilt_deg, roll_deg, pose_source(sfm|merged|pose_graph|interpolated), label{tr,en}, area{tr,en}, pano_key`; **Edge** (LineString): `id, from, to, kind(outdoor|indoor|entrance|stairs|elevator), length_m, cost_s, length_source(sfm|osm|estimate), yaw_from_deg, yaw_to_deg, bidirectional`.
   - `heading_deg` = compass bearing of pano yaw 0 (front-face centre): `atan2(E,N)` of `R_world_from_cam·[0,0,1]`; `bearing = (ath + heading_deg) mod 360`; tilt/roll from residual gravity → PSV `sphereCorrection`.
   - `cost_s = length / 1.3 m/s` + stairs penalty; stairs/elevator from labels or Δz > 2 m.
   - **Validate:** outdoor connected, no edge > 60 m, no edge crosses a footprint, every building ≥ 1 entrance, A Blok → Kütüphane within 15% of OSM footpath distance.
   - `pois.json`: `id, name{tr,en}, aliases, category, building, floor, node_id, search_key=normalize_tr()`.
   - `amap export panos`: faces in PSV convention, WebP 1300/650 px + 512×256 equirect preview → R2 via `amap publish` (content-hashed keys, immutable cache).

### Phase 3 — FastAPI backend
- Migration `supabase/migrations/20261006000000_init.sql`: extensions postgis, vector, pg_trgm; tables `buildings`, `nodes` (PointZ, GiST), `edges`, `pois` (trigram), `chunks` (`vector(768)` HNSW cosine, `content_hash` unique, `lang`, `source_url`), `answer_cache`; RLS on, API role read-only (+ write `answer_cache`); session pooler. Loader `amap load-db --env local|prod`.
- Layout `apps/api/src/amap_api/`: `main.py` (`create_app`, lifespan loads NetworkX graph), `settings.py` (pydantic-settings: `DATABASE_URL, GROQ_API_KEY, GEMINI_API_KEY, CORS_ORIGINS, ASSET_BASE_URL, GRAPH_SOURCE`), `db.py` (psycopg 3 async pool), `routers/{graph,pois,route,weather,chat,health}.py`, `services/{routing,steps,poi_search,weather}.py`, `services/rag/`, `export_openapi.py`.
- Endpoints: `GET /health`, `GET /graph?scope=outdoor|all` (ETag), `GET /buildings`, `GET /pois?q&lang&limit&category` (alias → prefix → trigram), `POST /route {from:{node_id}|{poi_id}|{lat,lng}, to, avoid_stairs, lang}` → `{node_ids, length_m, duration_s, geometry, steps[{node_id, turn, distance_m, landmark_poi_id, text}]}` (404 unknown, 422 no path), `GET /weather` (Open-Meteo, 10-min TTL, stale-on-error, attribution), `POST /chat` (SSE, Phase 5).
- Routing: `nx.astar_path`, heuristic = ENU distance / speed, `avoid_stairs` via weight fn returning `None`; lat/lng snaps to nearest outdoor/entrance node; turns: ±20° straight, 20–60° slight, 60–150° turn, > 150° U-turn; merge straight runs.
- **Accept:** route p95 ≤ 50 ms, idle RAM ≤ 300 MB, no OpenAPI drift.

### Phase 4 — Web app (premium UI)
- `apps/web/src/`: `app/[locale]/{layout,page}.tsx` (landing), `app/[locale]/map/page.tsx`, `proxy.ts` (next-intl), `messages/{tr,en}.json`, `lib/api/{schema.d.ts,client.ts}` (openapi-fetch + TanStack Query), `lib/geo/enu.ts` (proj4).
- `features/campus3d/`: `CampusCanvas`, `Buildings` (merged extrusions), `TexturedBuilding` (meshopt + KTX2), `RouteLine` (tube + `uProgress` draw-on shader, glow), `NodeMarkers`, `CameraRig`, view toggle stylized ↔ textured.
- `features/route/`: `RouteSearch` (shadcn combobox, debounced `/pois`, swap, avoid-stairs, pick on map), `StepList` (aria-live text alternative), `routeStore.ts` (zustand, URL `?from&to`).
- `features/walkthrough/`: PSV 5 cubemap adapter + virtual-tour plugin (`positionMode:'gps'`, `renderMode:'3d'`), `buildTourNodes.ts` (node → `{id, panorama, gps, sphereCorrection:{pan:-heading,tilt,roll}, links}`; sign convention locked by unit test + one landmark check), route mode highlights next arrow + auto-turn, 3D mini-map inset.
- `features/environment/`: live sun & weather (below). `features/chat/`: AI SDK `useChat` against `POST /chat` (Vercel AI data-stream protocol from pydantic-ai `VercelAIAdapter`).
- Design system: OKLCH tokens, type scale, spacing, motion tokens (150/250/400/800 ms) in Tailwind `@theme`; "day" + "night campus" themes; Motion for micro-interactions.
- **Accept:** `/map` JS < 250 KB gz before 3D chunk, LCP ≤ 2.5 s on 4G, `tsc --noEmit` clean.

### Phase 5 — AI assistant + RAG
- Corpus `pipeline/src/amap_pipeline/rag/`: `labels.py` (building → floor → room docs), `buildings.py`, `vision.py` (Gemini Flash-Lite on ~4 downscaled side faces/pano → JSON `{landmarks, signage_text, description_tr, description_en}`, resumable JSONL keyed `(pano, prompt_version)`, ≤ 10 RPM + daily cap, tenacity), `web_docs.py` (only `configs/rag_sources.yaml` URLs on aydin.edu.tr, robots.txt, 1 req/2 s), `chunk.py` (300–500 tokens, 50 overlap, per language), `embed.py` (`gemini-embedding-2` 768d, content-hash cache) → `amap rag load`.
- Agent `apps/api/src/amap_api/services/rag/`: `Agent(FallbackModel(GroqModel('openai/gpt-oss-120b'), GoogleModel('gemini-3.5-flash-lite')))`, `parallel_tool_calls=False`, prompts `prompts/assistant.{tr,en}.md`; tools `search_places` (trigram + vector), `get_route` (also emits `route` SSE so the map draws it), `describe_route` (steps + landmarks); budget ≤ 3K tokens (last 4 turns, ≤ 1.5K retrieved); answer cache (LRU + Postgres, key `normalize(q)+lang`); degraded keyword-only mode; streaming via pydantic-ai `VercelAIAdapter` (AI SDK data-stream protocol) consumed by AI SDK `useChat` in `features/chat/` — `get_route` tool results render the route on the map (verify AI SDK package versions at implementation); per-IP token bucket; 1,000-char limit; UI notice that free-tier prompts may be used by Google.
- Tests with pydantic-ai `TestModel`/`FunctionModel` (no network). Eval `apps/api/evals/` 30 TR/EN questions: context recall ≥ 0.8, faithfulness ≥ 0.85, correct tool ≥ 90%, first token p95 ≤ 3 s (Ragas 0.4.3, manual workflow).

### Phase 6 — Landing, polish, deploy
- Landing `features/landing/VoyageCanvas.tsx` (one R3F canvas, motionsites "space-voyage" logic, closer start): L0 sky/clouds shader → L1 stylized Istanbul (OSM coastline/landuse baked + city-light particles) → L2 Florya roads/coast + glowing campus outline → L3 real campus massing → L4 portal into an entrance pano (`useCubeTexture` crossfade) → hand-off to `/map?node=…`. Camera on `CatmullRomCurve3` + look-at curve, scrubbed ScrollTrigger on ~600vh pinned section, Lenis driven by GSAP ticker, bilingual overlays; reduced motion → 4 crossfading stills; low power → dpr 1, no particles.
- Budgets: landing first view < 3 MB; 60 fps desktop / ≥ 30 fps mid mobile; Lighthouse mobile ≥ 80 landing, ≥ 90 map shell; WCAG 2.2 AA (keyboard comboboxes, skip links, step list).
- Deploy: Vercel (root `apps/web`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_ASSET_BASE_URL`); Render `render.yaml` (`uv sync --package amap-api --frozen --no-dev`, `uvicorn amap_api.main:app`, health `/health`); R2 bucket `aydin-map-assets` (CORS via wrangler, custom domain if available); Supabase `db push` + `amap load-db --env prod`; `keepalive.yml` daily `/health` (prevents Supabase pause), "waking up" UI for Render cold starts.

### Phase 7 — Later
Indoor navigation (floor dimension, stairs/elevator, floor selector, plans sliced from point cloud) · photo localization (retrieval + LightGlue vs pano faces, inference only) · Google Photorealistic 3D Tiles "Gerçek görünüm" layer (needs Google Cloud key; stream only, no extraction, attribution, separate from OSM layers).

## Feature: live sun & weather

- `suncalc` + campus lat/lng (40.9915, 28.7971, Europe/Istanbul) → directional light dir/intensity/colour temp, drei `<Sky>`, hemisphere light, shadows; smooth day → golden → blue hour → night.
- Night: stars, emissive windows (stylized), lamp lights along graph, route glow (bloom).
- Open-Meteo via API (`weather_code, cloud_cover, precipitation, wind, visibility`) → clouds, fog, instanced wind-tilted rain/snow, wet roughness, overcast dimming. Attribution in footer.
- Live default + time slider + weather override + "back to live"; reduced-motion/mobile → no particles.
- Textured mesh + 360 have baked daylight → colour grade only; 360 night grade ≤ 25%.
- Files: `apps/web/src/features/environment/{useSunPosition.ts,useWeather.ts,EnvironmentRig.tsx,WeatherParticles.tsx,TimeOfDaySlider.tsx}`, `apps/api/.../routers/weather.py`, `services/weather.py`.

## Stack pins (verified 2026-10-06)

- **Pipeline:** pycolmap/COLMAP 4.2.1 (`brew install colmap`, `pip install "pycolmap[panorama]"`), OpenMVS 2.4.0 `OpenMVS_macOS_arm64.zip` (unsigned → `xattr -dr com.apple.quarantine`), Open3D 0.20, osmnx 2.1, pyproj 3.8, shapely 2.1, py360convert 1.0.4, `@gltf-transform/cli` 4.5 (+ KTX-Software 4.4), gltfpack 1.3. Optional inference: Depth Pro (MPS), MoGe-2 (MIT), DA-V2 Small (Apache); avoid CC-BY-NC models. Torch device order CUDA → MPS → CPU.
- **API:** FastAPI 0.142 (`fastapi[standard]`, `fastapi.sse`), pydantic-settings 2.15, NetworkX 3.7, psycopg 3.3 + `pgvector` 0.5, pydantic-ai-slim[google,groq] 2.54, google-genai 2.28, groq 1.7, Ragas 0.4.3. Avoid LiteLLM (2026 supply-chain incident).
- **Web:** Node 24 LTS (.nvmrc; local Node 26 OK), pnpm 12, next 16.3.8, react 19.3, **typescript ~5.9.3**, tailwindcss 4.3.3, shadcn 4.21 (Base UI), **three 0.185.1** (PSV peer), @react-three/fiber 9.8.1, drei 10.7.9, @react-three/postprocessing 3.1.3, @photo-sphere-viewer/* 5.15.1, gsap 3.15 + @gsap/react, lenis 1.3.26, motion 14, next-intl 4.14.9, openapi-typescript 7.13 + openapi-fetch 0.17, zustand, @tanstack/react-query, suncalc, proj4; vitest 5 + vite 8, RTL 16, jsdom, @playwright/test 1.63, @axe-core/playwright.
- **Infra limits:** Groq 30 RPM / 1000 RPD / **8K TPM**; Gemini free ~500 RPD Flash-Lite; Supabase 500 MB DB / pauses after 7 days; R2 10 GB free egress-free; Render 512 MB, sleeps after 15 min, no IPv6 → Supabase session pooler.

## Data sources & licenses

Tour (core, permission; never committed) · OSM via osmnx/Overpass (ODbL attribution, share-alike for derived DB) · Overture buildings (optional heights) · aydin.edu.tr public docs for RAG (robots.txt, cite sources) · Open-Meteo (CC BY 4.0) · Google 3D Tiles (Phase 7, ToS limits) · İBB 3B İstanbul not used (restrictive license). OpenMVS AGPL → external binary only (ADR-0002).

## Top risks → mitigations

1. SfM fragments (wide baselines, ~14 px/°) → time-boxed fallback ladder; OSM footway fallback still ships routes.
2. Wrong face orientation → seam test is a hard gate.
3. Rate limiting during exports → authorised session, polite rate, resumable queue, checksums.
4. Copyright leak → gitignore + pre-commit + CI guard + gitleaks, synthetic fixtures only.
5. Scale/georef error → three independent cues with numeric gates.
6. Dense quality/time → massing is the primary visual; textured GLB only where quality passes; per-building runs overnight.
7. Free-tier LLM limits → token budget, cache, fallback, keyword-only mode.
8. Render 512 MB / cold starts; Supabase pause → slim deps, waking-up UI, keepalive cron.
9. Version pin conflicts (three/PSV/R3F, TS) → exact pins, grouped Dependabot, `next build` in CI.
10. Turkish İ/ı search → shared `normalize_tr()` (pipeline, DB, API) with tests.

## Verification

- **Every change:** `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -m "not db and not recon"`; `pnpm -r lint && pnpm -r exec tsc --noEmit && pnpm -r test`; contracts drift check; guard job (no `data/` tracked).
- **Pipeline (manual, on the Mac):** `amap tiles verify --set spike35` (0 missing/corrupt) → `amap rig seam-test` (G1) → `amap sfm --config spike.yaml && amap sfm report` (G2–G5, OSM overlay HTML opened in browser) → `amap georef` (median ≤ 3 m) → `amap graph export` (validators pass, A Blok → Kütüphane ≈ OSM footpath ±15%).
- **API:** `uv run fastapi dev` → `curl /health`, `POST /route` A Blok → Kütüphane returns steps; `pytest -m db` against `supabase start`.
- **Web:** `pnpm --filter web dev` → Playwright E2E (search → route drawn → step list → walkthrough opens → locale switch, axe clean); manual visual check with browser screenshots (day/night/rain presets, mobile viewport); Lighthouse budgets.
- **AI:** pydantic-ai TestModel unit tests; manual `rag-eval` workflow meets targets.

## User actions needed

- Phase 1: keep the 360 tour tab open in Chrome during downloads; `brew install colmap` approval.
- Phase 2: pick 2–3 georef control points (~15 min in geojson.io); review per-building textured GLBs.
- Phase 3–6: create accounts/keys — Supabase, Groq, Gemini, Cloudflare R2, Vercel, Render (secrets via env / GitHub secrets, never in code); confirm public re-hosting of panoramas is covered by the permission; confirm copyright holder name for attribution.

## First 10 steps

1. `git init`, `.gitignore` (data/, .env*), verify no data tracked.
2. Root workspaces + tooling + pre-commit guard + LICENSE/community files/templates + `docs/data-policy.md`.
3. Port `analyze_tour.py` → `amap_pipeline.tour` + tests; `amap tour build/select`.
4. Minimal `ci.yml` with guard; first Conventional Commit; `gh repo create aydin-university-map --public --source . --push`; enable security features.
5. Tile sink + `fetch-tiles.js` with tests (preflight/PNA, token, checksum, atomic write, resume).
6. Export spike35 from the authorised browser session; `amap tiles verify`.
7. `uv sync --extra recon`, `brew install colmap`, `amap rig seam-test` → `rig_config.json`.
8. `amap sfm` + `amap sfm report` (metrics, OSM overlay, p28 check).
9. Go/no-go review with the user; fallbacks if needed; ADR-0003.
10. Background-download outdoor 100; scaffold `apps/web` (create-next-app, remove nested workspace file) and `apps/api` (`/health`, OpenAPI export, drift check).

## Reuse from GitHub (checked 2026-10-06; licences verified)

| Repo (licence) | What we reuse | Where |
|---|---|---|
| colmap/colmap ≥ 4.2 (BSD-3) | `pycolmap.panorama.create_pano_rig_config` pattern (`RigConfig`/`RigConfigCamera`/`Rigid3d`) with our 6 fixed krpano rotations (no virtual rendering needed → 4.2.1 OK; #4790 fix only matters for the equirect render path), `apply_rig_config`, `global_mapping`, **`model_aligner --alignment_type enu-plane`** / `align_reconstruction_to_locations` for control-point georef | `recon/sfm.py`, `geo/align.py` |
| mapillary/OpenSfM (BSD-2) | Port `align.py` helpers (`estimate_ground_plane`, `get_horizontal_and_vertical_directions`, orientation-prior similarity) for gravity/ground; fallback spherical SfM | `geo/align.py`, fallback ladder |
| cdcseacave/openMVS v2.4.0 (AGPL, external binary) | `InterfaceCOLMAP → Densify → ReconstructMesh → TextureMesh --export-type glb`; `scripts/python/MvsScalablePipeline.py` sub-scene splitting to bound RAM | `recon/dense.py` |
| zeux/meshoptimizer gltfpack 1.3 (MIT) | One-shot web optimisation `gltfpack -i in.glb -o out.glb -si 0.2 -cc -tc -kn` (glTF-Transform 4.5 when scripted control is needed) | `recon/dense.py` |
| mistic100/Photo-Sphere-Viewer 5.15.1 (MIT) | `cubemap-adapter` order = krpano `l|f|r|b|u|d` (serve faces directly, `flipTopBottom` if needed); VirtualTourPlugin `positionMode:'gps'` + `renderMode:'3d'` places arrows from our WGS84 node positions; server mode `getNode` | `features/walkthrough/` |
| gboeing/osmnx (MIT) | Footprints + `network_type="walk"` footways as NetworkX graph (georef target, last-resort edges) | `geo/osm.py` |
| pydantic/pydantic-ai 2.54 (MIT) | `examples/.../rag.py` (pgvector + asyncpg + `@agent.tool`); **`VercelAIAdapter.dispatch_request`** streams the Vercel AI data-stream protocol from FastAPI → web uses AI SDK `useChat` (tool parts render the route on the map) instead of a custom SSE client | `services/rag/`, `routers/chat.py`, `features/chat/` |
| vstorm-co/full-stack-ai-agent-template (MIT) | Layout of `agents/tools/rag_tool.py`, conversation persistence ideas | reference |
| darkroomengineering/satus (MIT; Next 16.3 + R3F 9.8 + GSAP 3.15 + Lenis 1.3) | `lib/webgl` setup and Lenis ↔ GSAP ticker wiring (port from bun to pnpm) | `features/landing/`, app shell |
| 14islands/r3f-scroll-rig (MIT) | `GlobalCanvas` + `ViewportScrollScene` pattern if DOM-synced 3D sections are needed | landing (optional) |
| gkjohnson/three-geojson (MIT, GitHub-only) | Reference for precision-safe extrusion (float64 centering, constrained Delaunay); we implement our own small extruder to avoid a git dependency | `features/campus3d/Buildings` |
| wass08/wawa-vfx (MIT) / SahilK-027/Elemental-Serenity (MIT) | R3F particle emitters for rain/snow; shader references | `features/environment/WeatherParticles` |
| takram three-geospatial (MIT) | Optional physically-based `<Atmosphere date>` sky (heavier; default stays drei `<Sky>` + suncalc) | environment (optional) |
| JamesLMilner/terra-draw (MIT) | Small admin editor to fix/bridge graph edges if SfM leaves gaps | optional `apps/web/src/app/[locale]/admin/graph` |
| fastapi/full-stack-fastapi-template (MIT) | Backend layout, uv usage, `test-backend.yml`/`playwright.yml` CI patterns | `apps/api`, `.github/workflows` |
| vintasoftware/nextjs-fastapi-template (MIT) | OpenAPI → TS regeneration watcher + CI idea (we keep openapi-typescript + openapi-fetch) | `packages/contracts`, CI |

**Avoid / flag:** dezoomify-rs (GPL, not needed — own sink), KRPano_DL & unlicensed templates (ideas only), pandana (AGPL), pgRouting (GPL), OSMBuildings (stale), marzipano (archived), mkkellogg splats (unmaintained). Open-Meteo free API is **non-commercial** only — fine for this project; revisit if it ever becomes commercial.
