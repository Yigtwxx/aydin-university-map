import { expect, type Page, test as base } from '@playwright/test';

/** Mobile project: the panel is a bottom sheet and 360° opens full screen. */
export const test = base.extend<{ mobile: boolean }>({
  // `provide`, not Playwright's usual `use`: the React hooks lint reads that
  // name as a hook call.
  mobile: async ({}, provide, testInfo) => {
    await provide(testInfo.project.name === 'mobile');
  },
});

export { expect };

const LOADING = { tr: 'Kampüs hazırlanıyor', en: 'Preparing the campus' };

/** Opens the map and waits for the campus (graph and buildings) to load. */
export async function openMap(page: Page, path = '/tr/map') {
  await page.goto(path);
  await campusReady(page, path.startsWith('/en') ? 'en' : 'tr');
}

/** The loading splash is gone: the panel and the map can be used. */
export async function campusReady(page: Page, locale: 'tr' | 'en' = 'tr') {
  await expect(page.getByText(LOADING[locale])).toBeHidden({
    timeout: 60_000,
  });
}

/** Types into a place search and picks the suggestion named `option`. */
export async function pickPlace(
  page: Page,
  field: string,
  query: string,
  option: RegExp,
) {
  const input = page.getByRole('combobox', { name: field, exact: true });
  await input.click();
  await input.fill(query);
  await page.getByRole('option', { name: option }).click();
  await expect(page.getByRole('listbox')).toBeHidden();
}

/** Destination "E Blok Giriş", start "Kampüs Girişi", searched like a visitor. */
export async function planRoute(page: Page) {
  await pickPlace(page, 'Varış yeri ara', 'E Blok', /^E Blok Giriş/);
  await pickPlace(page, 'Başlangıç', 'Kampüs Girişi', /^Kampüs Girişi/);
  await expectRoute(page, 'tr');
}

const START = { tr: '360° yürüyüşü başlat', en: 'Start the 360° walk' };
const STEPS = { tr: 'Adımlar', en: 'Steps' };

/** A drawn route: the summary's start button and at least two steps. */
export async function expectRoute(page: Page, locale: 'tr' | 'en') {
  await expect(page.getByRole('button', { name: START[locale] })).toBeVisible();
  const steps = page
    .getByRole('list', { name: STEPS[locale] })
    .getByRole('listitem');
  await expect(steps.nth(1)).toBeAttached();
}

export function routeSteps(page: Page, locale: 'tr' | 'en' = 'tr') {
  return page.getByRole('list', { name: STEPS[locale] }).getByRole('button');
}
