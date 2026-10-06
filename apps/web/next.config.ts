import path from 'node:path';
import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const repoRoot = path.join(__dirname, '..', '..');

const nextConfig: NextConfig = {
  typedRoutes: true,
  // pnpm workspace: the lockfile lives at the repository root.
  turbopack: { root: repoRoot },
  outputFileTracingRoot: repoRoot,
};

export default createNextIntlPlugin()(nextConfig);
