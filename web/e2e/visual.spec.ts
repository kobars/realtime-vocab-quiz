// AI-ASSISTED: screenshot baselines of every screen at each project's width and color scheme.
import { expect, test } from '@playwright/test'
import { SCREENS } from './fixtures/screens'

for (const screen of SCREENS) {
  test(`${screen.name} looks as in its baseline`, async ({ page }) => {
    await screen.reach(page)
    await expect(page).toHaveScreenshot(`${screen.name}.png`, { fullPage: true })
  })
}
