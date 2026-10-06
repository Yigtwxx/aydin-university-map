import {
  campusReady,
  expect,
  expectRoute,
  openMap,
  planRoute,
  routeSteps,
  test,
} from './fixtures';

test.describe('shareable walking routes', () => {
  test('searching a destination and a start draws the route and puts it in the URL', async ({
    page,
  }) => {
    await openMap(page);
    await planRoute(page);
    await expect(page).toHaveURL(/[?&]from=[\w-]+/);
    await expect(page).toHaveURL(/[?&]to=[\w-]+/);
    await expect(page).toHaveURL(/[?&]stairs=0/);
  });

  test('reloading the link restores the same route', async ({ page }) => {
    await openMap(page);
    await planRoute(page);
    const shared = page.url();

    await page.reload();
    await campusReady(page);
    await expectRoute(page, 'tr');
    await expect(
      page.getByRole('combobox', { name: 'Varış', exact: true }),
    ).toHaveValue('E Blok Giriş');
    await expect(
      page.getByRole('combobox', { name: 'Başlangıç', exact: true }),
    ).toHaveValue('Kampüs Girişi');
    expect(page.url()).toBe(shared);
  });

  test('"Copy link" copies the absolute route link', async ({
    page,
    context,
  }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await openMap(page);
    await planRoute(page);
    await page.getByRole('button', { name: 'Bağlantıyı kopyala' }).click();
    await expect(
      page.getByText('Rota bağlantısı panoya kopyalandı.'),
    ).toBeAttached();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toBe(page.url());
  });

  test("a step's 360° thumbnail opens the panorama viewer", async ({
    page,
    mobile,
  }) => {
    await openMap(page);
    await planRoute(page);
    await routeSteps(page).first().click();

    // Phones: a full-screen dialog; desktop: an inset next to the panel.
    const viewer = page.getByRole(mobile ? 'dialog' : 'region', {
      name: '360° görünüm',
    });
    await expect(viewer).toBeVisible();
    await expect(viewer.getByText(/^Adım 1\/\d+/)).toBeVisible();
    // Photo Sphere Viewer renders into its own canvas (WebGL).
    await expect(viewer.locator('canvas')).toBeAttached();
    await expect(page).toHaveURL(/[?&]step=0/);

    // Walking on replaces the history entry instead of adding one.
    const entries = await page.evaluate(() => history.length);
    await viewer.getByRole('button', { name: 'Sonraki adım' }).click();
    await expect(viewer.getByText(/^Adım 2\/\d+/)).toBeVisible();
    await expect(page).toHaveURL(/[?&]step=1/);
    expect(await page.evaluate(() => history.length)).toBe(entries);

    await viewer.getByRole('button', { name: '360° görünümü kapat' }).click();
    await expect(viewer).toBeHidden();
    await expect(page).not.toHaveURL(/[?&]step=/);
  });

  test('switching TR to EN keeps the route and translates the UI', async ({
    page,
  }) => {
    await openMap(page);
    await planRoute(page);
    const query = new URL(page.url()).search;

    await page.getByRole('link', { name: 'EN', exact: true }).click();
    await expect(page).toHaveURL(
      (url) => url.pathname === '/en/map' && url.search === query,
    );
    await expect(page.getByRole('tab', { name: 'Directions' })).toBeVisible();
    await expectRoute(page, 'en');
    await expect(
      page.getByRole('combobox', { name: 'Destination', exact: true }),
    ).toHaveValue('E Block Entrance');
    await expect(
      page.getByRole('combobox', { name: 'Start', exact: true }),
    ).toHaveValue('Campus Entrance');
  });
});

test.describe('mobile bottom sheet', () => {
  test.skip(({ mobile }) => !mobile, 'phones only');

  test('snaps with its handle, lowers with Escape and rises for typing', async ({
    page,
  }) => {
    await openMap(page);
    const sheet = page.locator('aside');
    await expect(sheet).toHaveAttribute('data-snap', 'peek');
    const height = async () => (await sheet.boundingBox())?.height ?? 0;
    await expect.poll(height).toBeLessThan(160);

    const handle = page.getByRole('button', { name: 'Paneli büyüt' });
    await expect(handle).toHaveAttribute('aria-expanded', 'false');
    await handle.click();
    await expect(sheet).toHaveAttribute('data-snap', 'half');
    await expect.poll(height).toBeGreaterThan(380);

    const toFull = page.getByRole('button', { name: 'Paneli tam boy aç' });
    await toFull.click();
    await expect(sheet).toHaveAttribute('data-snap', 'full');

    await page.getByRole('button', { name: 'Paneli küçült' }).press('Escape');
    await expect(sheet).toHaveAttribute('data-snap', 'half');
    await page
      .getByRole('button', { name: 'Paneli tam boy aç' })
      .press('Escape');
    await expect(sheet).toHaveAttribute('data-snap', 'peek');

    // Focusing the search makes room for its suggestions.
    await page.getByRole('combobox', { name: 'Varış yeri ara' }).click();
    await expect(sheet).toHaveAttribute('data-snap', 'full');
  });

  test('a drag flicks the sheet to the next snap', async ({ page }) => {
    await openMap(page);
    const sheet = page.locator('aside');
    const handle = page.getByRole('button', { name: 'Paneli büyüt' });
    const box = await handle.boundingBox();
    if (!box) throw new Error('no sheet handle');
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let i = 1; i <= 6; i++) await page.mouse.move(x, y - i * 30);
    await page.mouse.up();
    await expect(sheet).toHaveAttribute('data-snap', /half|full/);
  });
});
