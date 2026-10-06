import { readFileSync } from 'node:fs';
import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

/**
 * Browser E2E: the real API (offline assistant model, no database, the
 * published graph and assets) and the web app, on ports of their own so they
 * run next to `./start.sh` (8000/3000).
 *
 * Web server: a production build in CI. Locally `next dev`, unless another
 * `next dev` already runs in this directory (start.sh's): Next.js allows one
 * per project, so then it falls back to a build. `E2E_WEB_MODE=dev|prod`
 * forces either.
 */

const CI = Boolean(process.env.CI);
const API_PORT = 8010;
const WEB_PORT = 3010;
const API_URL = `http://localhost:${API_PORT}`;
const WEB_URL = `http://localhost:${WEB_PORT}`;
const ASSETS = 'https://aydin-campus-assets.pages.dev';
const WEB_DIR = __dirname;
const REPO_ROOT = path.join(WEB_DIR, '..', '..');

function devServerRunning(): boolean {
  try {
    const lock = JSON.parse(
      readFileSync(path.join(WEB_DIR, '.next', 'dev', 'lock'), 'utf8'),
    ) as { pid?: unknown };
    if (typeof lock.pid !== 'number') return false;
    process.kill(lock.pid, 0);
    return true;
  } catch {
    return false;
  }
}

const webMode =
  process.env.E2E_WEB_MODE === 'dev' || process.env.E2E_WEB_MODE === 'prod'
    ? process.env.E2E_WEB_MODE
    : CI || devServerRunning()
      ? 'prod'
      : 'dev';

/**
 * New headless Chromium (the full browser). It uses the GPU where there is one
 * (a developer's machine); CI runners have none, so WebGL runs on SwiftShader
 * there, which has to be allowed explicitly. `E2E_SWIFTSHADER=1` forces it.
 */
const swiftShader = CI || process.env.E2E_SWIFTSHADER === '1';
const chromium = {
  ...devices['Desktop Chrome'],
  channel: 'chromium',
  launchOptions: {
    args: swiftShader
      ? [
          '--use-angle=swiftshader',
          '--enable-unsafe-swiftshader',
          '--ignore-gpu-blocklist',
        ]
      : [],
  },
};

export default defineConfig({
  testDir: './e2e',
  // Software-rendered WebGL keeps the main thread busy: be patient there.
  timeout: swiftShader ? 180_000 : 90_000,
  expect: { timeout: swiftShader ? 45_000 : 20_000 },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 1 : 2,
  reporter: CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: WEB_URL,
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...chromium, viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: {
        ...chromium,
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
        userAgent: devices['Pixel 7'].userAgent,
      },
    },
  ],
  webServer: [
    {
      name: 'api',
      command: `uv run uvicorn amap_api.main:create_app --factory --port ${API_PORT}`,
      cwd: REPO_ROOT,
      url: `${API_URL}/health`,
      // Explicit values win over the repo-root .env, which the API also reads.
      env: {
        AMAP_ASSISTANT_MODEL: 'offline',
        GRAPH_SOURCE: `${ASSETS}/graph.geojson`,
        ASSET_BASE_URL: ASSETS,
        ASSET_DIR: '',
        CORS_ORIGINS: WEB_URL,
        AMAP_API_DATABASE_URL: '',
      },
      reuseExistingServer: !CI,
      timeout: 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      name: 'web',
      command:
        webMode === 'prod'
          ? `pnpm --filter web build && pnpm --filter web start -p ${WEB_PORT}`
          : `pnpm --filter web exec next dev -p ${WEB_PORT}`,
      cwd: REPO_ROOT,
      url: `${WEB_URL}/tr/map`,
      env: {
        NEXT_PUBLIC_API_URL: API_URL,
        NEXT_PUBLIC_ASSET_BASE_URL: ASSETS,
        NEXT_TELEMETRY_DISABLED: '1',
      },
      reuseExistingServer: !CI,
      timeout: webMode === 'prod' ? 360_000 : 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
});
