// AI-ASSISTED: the design system's component gallery matches its baseline, passes axe (WCAG 2.2 AA, contrast included) and fits every width.
import { expect, test } from '@playwright/test'
import { expectAccessible, GALLERY_URL } from './stack'

/** Each of the two theme panels shows one toast of each type. */
const TOASTS = 8

test.beforeEach(async ({ page }) => {
  // The page is over 11,000 px tall at 1280 px and twice that at 320: a full-page screenshot or axe scan of it takes
  // several times as long as one of an app screen, more so under emulation on an arm64 machine.
  test.slow()
  await page.goto(GALLERY_URL)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Clay design system')
  await expect(page.locator('[data-sonner-toast][data-mounted="true"]')).toHaveCount(TOASTS)
  await page.evaluate(() => document.fonts.ready)
})

test('the gallery looks as in its baseline', async ({ page }, testInfo) => {
  // The page shows both themes side by side, and one column below 1024 px would pass Chromium's screenshot height.
  test.skip(!testInfo.project.name.startsWith('1280-'), 'the gallery has a baseline at 1280 px only')
  await expect(page).toHaveScreenshot('gallery.png', { fullPage: true })
})

test('the gallery passes axe and fits the width', async ({ page }) => {
  await expectAccessible(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0)
})
