// AI-ASSISTED: screenshot baselines of every screen at each project's width and color scheme, plus the layout checks a full-page screenshot cannot show: one outline around the phone tabs and the pinned row under the top 10.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { SCREENS } from './fixtures/screens'

for (const screen of SCREENS) {
  test(`${screen.name} looks as in its baseline`, async ({ page }) => {
    await screen.reach(page)
    await expect(page).toHaveScreenshot(`${screen.name}.png`, { fullPage: true })
  })
}

const leaderboard = SCREENS.find((screen) => screen.name === 'leaderboard')

test('the selected phone tab draws no outline inside the tab track\'s outline', async ({ page }) => {
  // The leaderboard screen skips itself from 1024 px, where there are no tabs.
  await leaderboard?.reach(page)
  // Unfocused: a focused tab's band covers its outline on purpose.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  const borders = await page.locator('[role="tablist"], [role="tab"][aria-selected="true"]').evaluateAll((elements) =>
    elements.map((element) => getComputedStyle(element).borderTopColor))
  expect(borders).toHaveLength(2)
  expect(borders[0]).not.toBe('rgba(0, 0, 0, 0)')
  expect(borders[1]).toBe('rgba(0, 0, 0, 0)')
})

test('the pinned row sits under the tenth row, never over a row', async ({ page }) => {
  await leaderboard?.reach(page)
  const rows = page.getByRole('region', { name: strings.leaderboard.title }).locator('li')
  await expect(rows).toHaveCount(10)
  const pinned = await page.getByTestId('pinned').boundingBox()
  const tenth = await rows.nth(9).boundingBox()
  expect(pinned?.y ?? 0).toBeGreaterThan((tenth?.y ?? Infinity) + (tenth?.height ?? 0))
})
