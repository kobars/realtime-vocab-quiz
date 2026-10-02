// AI-ASSISTED: every screen has no WCAG 2.2 AA violation, no sideways scroll (also at 200% zoom), 44 px targets and a visible focus ring.
import { expect, type Page, test } from '@playwright/test'
import { SCREENS } from './fixtures/screens'
import { expectAccessible } from './stack'

const TARGET_PX = 44
/** A 1280 px window at 200% zoom lays out like a 640 px one. */
const ZOOMED = { width: 640, height: 400 }
/** More than any screen has; the loop ends when the focus leaves the page or comes round again. */
const MAX_TAB_STOPS = 40
const INTERACTIVE = 'a[href], button, input, select, textarea, [role="tab"], [tabindex]:not([tabindex="-1"])'

async function expectNoSidewaysScroll(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0)
}

async function expectTargetSize(page: Page): Promise<void> {
  const small = await page.locator(INTERACTIVE).evaluateAll((elements, min) => elements.flatMap((element) => {
    const { width, height } = element.getBoundingClientRect()
    const shown = width > 0 && height > 0
    return shown && (width < min || height < min) ? [`${element.outerHTML.slice(0, 80)}: ${width}x${height}`] : []
  }), TARGET_PX)
  expect(small).toEqual([])
}

/**
 * Compares the focused element's outline and shadow with its look after a blur, then focuses it again so the next Tab
 * moves on from it. Returns the element and whether its look changed, or null when the focus has left the page.
 */
function focusLook(): { at: number; element: string; ring: boolean } | null {
  const element = document.activeElement
  if (!(element instanceof HTMLElement) || element === document.body) return null
  const look = () => {
    const style = getComputedStyle(element)
    return `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor} ${style.boxShadow}`
  }
  const focused = look()
  element.blur()
  const unfocused = look()
  element.focus()
  return { at: [...document.querySelectorAll('*')].indexOf(element), element: element.outerHTML.slice(0, 80), ring: focused !== unfocused }
}

for (const screen of SCREENS) {
  test(`${screen.name} passes axe, fits the width and has 44 px targets`, async ({ page }) => {
    await screen.reach(page)
    await page.clock.resume() // axe waits on timers
    await expectAccessible(page)
    await expectNoSidewaysScroll(page)
    await expectTargetSize(page)
    if ((page.viewportSize()?.width ?? 0) >= 1280) {
      await page.setViewportSize(ZOOMED)
      await expectNoSidewaysScroll(page)
    }
  })

  test(`${screen.name} shows a focus ring on each control the Tab key reaches`, async ({ page }) => {
    await screen.reach(page)
    // Tab from the top of the page, not from the element the screen focused.
    await page.evaluate(() => {
      document.body.tabIndex = -1
      document.body.focus()
      document.body.removeAttribute('tabindex')
    })
    const seen = new Set<number>()
    for (let stop = 0; stop < MAX_TAB_STOPS; stop += 1) {
      await page.keyboard.press('Tab')
      const focus = await page.evaluate(focusLook)
      if (focus === null || seen.has(focus.at)) break
      seen.add(focus.at)
      expect(focus.ring, focus.element).toBe(true)
    }
    expect(seen.size).toBeGreaterThan(0)
  })
}
