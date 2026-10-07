import { describe, expect, it, vi } from 'vitest';

import { EMPTY_FURNITURE, fetchFurniture } from './furniture';

const respond = (status: number, body?: unknown) =>
  vi.fn<typeof fetch>(async () =>
    body === undefined
      ? new Response(null, { status })
      : new Response(JSON.stringify(body), { status }),
  );

describe('fetchFurniture', () => {
  it('reads a missing asset (404) as no furniture, not an error', async () => {
    const fetchImpl = respond(404);
    await expect(fetchFurniture('/assets', fetchImpl)).resolves.toBe(
      EMPTY_FURNITURE,
    );
    expect(fetchImpl).toHaveBeenCalledWith('/assets/furniture.json');
  });

  it('fails on other errors', async () => {
    await expect(fetchFurniture('/assets', respond(500))).rejects.toThrow(
      /HTTP 500/,
    );
  });

  it('fills in the contract defaults a file leaves out', async () => {
    const data = await fetchFurniture(
      '/assets',
      respond(200, {
        schema_version: 1,
        generated_at: '2026-10-07T00:00:00Z',
        terraces: [
          {
            id: 't',
            outline: [
              [0, 0],
              [1, 0],
              [0, 1],
            ],
            z_m: 1,
          },
        ],
        items: [{ id: 'b', kind: 'bench', at: [1, 2] }],
      }),
    );
    expect(data.terraces[0]!.edge).toBe('wall');
    expect(data.items[0]).toMatchObject({
      heading_deg: 0,
      length_m: null,
      base_z: 0,
    });
    expect(data.stairs).toEqual([]);
    expect(data.seating).toEqual([]);
  });
});
