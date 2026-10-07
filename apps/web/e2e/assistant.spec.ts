import { expect, expectRoute, openMap, test } from './fixtures';

test('the assistant answers a route question and fills the directions', async ({
  page,
}) => {
  // A shared link with ?panel=assistant opens the assistant tab.
  await openMap(page, '/tr/map?panel=assistant');
  await expect(page.getByRole('tab', { name: 'Asistan' })).toHaveAttribute(
    'aria-selected',
    'true',
  );

  const question = page.getByRole('textbox', { name: 'Bir soru yazın' });
  await question.fill("E Blok'a nasıl giderim?");
  await question.press('Enter');

  // The offline model calls get_route, then summarises the result.
  await expect(page.getByText("E Blok'a nasıl giderim?")).toBeVisible();
  await expect(page.getByText(/Rotayı haritaya çizdim/)).toBeVisible();
  const card = page.getByRole('button', { name: /E Blok/ }).filter({
    hasText: 'Adımlar',
  });
  await card.click();

  await expect(page.getByRole('tab', { name: 'Yol tarifi' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expectRoute(page, 'tr');
  await expect(
    page.getByRole('combobox', { name: 'Varış', exact: true }),
  ).toHaveValue(/E Blok/);
  await expect(page).toHaveURL(/[?&]from=[\w-]+/);
  await expect(page).toHaveURL(/[?&]to=[\w-]+/);
});
