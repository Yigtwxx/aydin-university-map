#!/usr/bin/env bash
# Start the Aydın Campus Map API (FastAPI, :8000) and web app (Next.js, :3000).
# Usage: ./start.sh            (Ctrl+C stops both)
#        API_PORT=8100 WEB_PORT=3100 ./start.sh
# Works with macOS' default bash 3.2.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

info() { printf '\033[1;34m›\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
need() {
  command -v "$1" >/dev/null 2>&1 || { printf 'missing %s: %s\n' "$1" "$2" >&2; exit 1; }
}

need uv "install from https://docs.astral.sh/uv/"
need pnpm "run: corepack enable"

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  warn "created .env from .env.example - fill in your keys"
fi

info "installing dependencies"
# --inexact keeps optional pipeline extras (pycolmap, open3d...) installed.
uv sync --all-packages --inexact --quiet
pnpm install --silent

info "generating API types"
uv run --quiet python -m amap_api.export_openapi 2>/dev/null
pnpm --filter web --silent gen:api

if [ ! -f data/out/graph.geojson ]; then
  warn "data/out/graph.geojson not found: route endpoints will answer 503"
  warn "build it with: uv run amap graph export --run <georeferenced run>"
fi

pids=()
cleanup() {
  trap - EXIT INT TERM
  printf '\n'
  info "stopping"
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ASSET_DIR="$ROOT/data/out" uv run uvicorn amap_api.main:create_app --factory --reload \
  --reload-dir apps/api/src --reload-dir packages/contracts/src \
  --port "$API_PORT" &
pids+=("$!")

# Browser token for the map's photoreal view (optional; read from .env
# without echoing it). Without it the photoreal toggle is hidden.
CESIUM_TOKEN="$(sed -n 's/^NEXT_PUBLIC_CESIUM_ION_TOKEN=//p' .env | tail -n 1)"

NEXT_PUBLIC_API_URL="http://localhost:$API_PORT" \
  NEXT_PUBLIC_ASSET_BASE_URL="http://localhost:$API_PORT/assets" \
  NEXT_PUBLIC_CESIUM_ION_TOKEN="$CESIUM_TOKEN" \
  pnpm --filter web dev --port "$WEB_PORT" &
pids+=("$!")

info "API  http://localhost:$API_PORT/docs"
info "Web  http://localhost:$WEB_PORT"

# Stop everything as soon as one of the two processes exits.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do
  sleep 1
done
