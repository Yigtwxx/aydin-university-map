import { campusReady, expect, test } from './fixtures';

test.describe('home page opening', () => {
  test('the campus builds itself, then the panel comes in', async ({
    page,
  }) => {
    await page.goto('/tr');
    await campusReady(page);
    const panel = page.locator('aside').first();
    // During the opening the panel is invisible and out of the tab order...
    await expect(panel).toHaveAttribute('inert', '');
    // ...then it fades in (a few seconds; longer in software WebGL, where
    // the opening's clock advances at most 1/30 s per frame).
    await expect(panel).not.toHaveAttribute('inert', '', { timeout: 150_000 });
    await expect(panel).toHaveCSS('opacity', '1');
  });

  test('plays once per session', async ({ page }) => {
    await page.goto('/tr');
    const panel = page.locator('aside').first();
    await expect(panel).not.toHaveAttribute('inert', '', { timeout: 150_000 });

    await page.reload();
    await campusReady(page);
    // No opening the second time: the panel follows the data at once.
    await expect(panel).not.toHaveAttribute('inert', '', { timeout: 20_000 });
  });
});
