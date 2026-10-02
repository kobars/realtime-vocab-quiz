// AI-ASSISTED: screenshot baselines of every screen at each project's width and color scheme, plus the layout checks a full-page screenshot cannot show: one outline around the phone tabs and nothing showing beside the pinned row.
import { expect, test } from '@playwright/test'
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

test('a row scrolling under the pinned row is hidden by its dock, never shown beside it', async ({ page }) => {
  await leaderboard?.reach(page)
  // Just above my row, inside the dock: the top 50 run on under it, so a row there would show around my row.
  const hit = await page.getByTestId('pinned').evaluate((row) => {
    const { left, width, top } = row.getBoundingClientRect()
    const element = document.elementFromPoint(left + width / 2, top - 4)
    return { inRow: element?.closest('li') !== null, inDock: element?.closest('[data-test="pinned-dock"]') !== null }
  })
  expect(hit).toEqual({ inRow: false, inDock: true })
})
