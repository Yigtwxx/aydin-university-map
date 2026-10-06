import createClient from 'openapi-fetch';

import type { paths } from './schema';

/** Base URL of the FastAPI service (set by start.sh / Vercel env). */
export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** Typed client generated from apps/api/openapi.json (`pnpm gen:api`). */
export const api = createClient<paths>({ baseUrl: apiBaseUrl });
