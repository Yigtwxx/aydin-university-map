import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { expect, openMap, planRoute, test } from './fixtures';

/** Serious and critical axe violations, without the WebGL canvas. */
async function seriousViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .exclude('canvas')
    .analyze();
  return violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
    }));
}

test.describe('accessibility (axe)', () => {
  test('/tr/map has no serious or critical violations', async ({ page }) => {
    await openMap(page);
    expect(await seriousViolations(page)).toEqual([]);
  });

  test('a drawn route has no serious or critical violations', async ({
    page,
  }) => {
    await openMap(page);
    await planRoute(page);
    expect(await seriousViolations(page)).toEqual([]);
  });
});
