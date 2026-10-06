import { apiBaseUrl } from './api/client';

/** Panoramas and massing: Cloudflare Pages in production, the API in development. */
export const assetBaseUrl =
  process.env.NEXT_PUBLIC_ASSET_BASE_URL ?? `${apiBaseUrl}/assets`;

export function panoFaceUrl(
  scene: string,
  face: 'l' | 'f' | 'r' | 'b' | 'u' | 'd',
  small = false,
) {
  return `${assetBaseUrl}/panos/${scene}/${face}${small ? '_s' : ''}.webp`;
}
