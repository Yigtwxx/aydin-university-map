# ADR-0004: Free hosting without a custom domain

- Status: accepted (supersedes the Cloudflare R2 choice in the design spec)
- Date: 2026-10-06

## Context

The maintainer does not want to buy a domain. Cloudflare R2 is only
production-ready behind a custom domain on a Cloudflare zone; its `r2.dev`
URLs are rate limited and meant for development. The app must serve about
5,000 static files: cube faces at two resolutions plus previews, and textured
GLB meshes of 5-15 MB per building, about 1.5-2 GB in total. The maintainer
confirmed the panoramas may be shown publicly.

## Decision

| Part | Host | URL |
|---|---|---|
| Web app (Next.js) | Vercel Hobby | `*.vercel.app` |
| API (FastAPI) | Render free | `*.onrender.com` |
| Panoramas + 3D models | **Cloudflare Pages** (direct upload with `wrangler pages deploy`) | `*.pages.dev` |
| Database | Supabase free | managed |

Cloudflare Pages free tier: unlimited bandwidth, 20,000 files per deployment,
25 MiB per file, global CDN, custom `_headers` for long-lived cache and CORS.
Assets are uploaded from `data/out/` by the pipeline and never enter git.

## Consequences

- No domain or payment is needed. All URLs are configured through
  `ASSET_BASE_URL` / `API_BASE_URL`, so a domain can be added later without
  code changes.
- Keep assets under the Pages limits: one GLB per building ≤ 25 MiB, faces as
  WebP. If the file count ever exceeds 20,000, split the assets into two Pages
  projects.
- Cache busting relies on content-hashed file names; `_headers` sets
  `Cache-Control: public, max-age=31536000, immutable` and
  `Access-Control-Allow-Origin` for the web origin.
