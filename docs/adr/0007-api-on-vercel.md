# ADR-0007: API on Vercel's Python runtime instead of Render

- Status: accepted (supersedes the API part of ADR-0004)
- Date: 2026-10-06

## Context

ADR-0004 put the FastAPI service on Render's free tier. Render sleeps after
15 minutes, takes about a minute to wake, caps memory at 512 MB, and needs
a dashboard step to apply the blueprint. The assistant now adds pydantic-ai
and the Groq and Gemini SDKs, and the database has to be reached over IPv4,
which means through the Supabase pooler.

## Decision

- The API runs as a Vercel project with root directory `apps/api`. The
  entrypoint is `amap_api.vercel:app` (`[tool.vercel]` in
  `apps/api/pyproject.toml`). Vercel's builder installs it from the
  workspace `uv.lock`, so `amap-contracts` comes along.
- Settings: region `fra1` (close to Supabase and İstanbul), fluid compute,
  and a 60 s function limit. That is enough for streamed assistant answers.
- Plain environment variables: `GRAPH_SOURCE` and `ASSET_BASE_URL` (Cloudflare
  Pages), and `CORS_ORIGINS`. Sensitive environment variables, piped from the
  local `.env` with the Vercel CLI so they are never printed:
  `GROQ_API_KEY`, `GEMINI_API_KEY` and `AMAP_API_DATABASE_URL`. The last
  one is the transaction-pooler URL of the least-privilege `amap_api` role.
- The web app is a second Vercel project (`apps/web`). Assets stay on
  Cloudflare Pages (`amap publish assets`).
- `render.yaml` stays as the fallback.

## Consequences

- Both apps deploy on every push to `main` and get preview deployments for
  pull requests.
- Cold starts load the graph from Pages once per instance.
- The rate limiter and the weather cache live per instance, so they are
  best effort.
- A daily GitHub Actions keepalive calls `/health`. That runs `select 1`
  and keeps the free Supabase project from pausing.
