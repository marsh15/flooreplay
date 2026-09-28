import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('the hero demonstration: stale evidence blocks, correction replays ready', async ({
  page,
}) => {
  await page.goto('/workbench?scenario=SCEN-HERO&revision=1')

  await page.getByRole('button', { name: 'Run replay' }).click()
  await expect(page.getByText('Needs context')).toBeVisible()
  await expect(page.getByText(/no policy ran|gate/i).first()).toBeVisible()

  // the corrected revision proposes O219 and passes every independent check
  await page.getByRole('button', { name: /SCEN-HERO@2$/ }).click()
  await page.getByRole('button', { name: 'Run replay' }).click()
  await expect(page.getByText('Ready for review')).toBeVisible()
  await expect(page.getByText(/Proposes O219/)).toBeVisible()
  for (const rule of ['C01', 'C07', 'C12']) {
    await expect(page.getByRole('row', { name: new RegExp(rule) })).toBeVisible()
  }
})

test('baseline proposes an occupied operator and is rejected by C07', async ({ page }) => {
  await page.goto('/workbench?scenario=SCEN-HERO&revision=2&config=CFG-BASELINE-V1')
  await page.getByRole('button', { name: 'Run replay' }).click()
  await expect(page.getByText('Rejected by constraint')).toBeVisible()
  await expect(page.getByRole('row', { name: /C07/ })).toBeVisible()
})
