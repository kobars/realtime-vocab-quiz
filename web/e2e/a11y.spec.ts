// AI-ASSISTED: every screen has no WCAG 2.2 AA violation, no sideways scroll (also at 200% zoom), 44 px targets and a visible focus ring.
import { expect, type Page, test } from '@playwright/test'
import { SCREENS } from './fixtures/screens'
import { expectAccessible } from './stack'

const TARGET_PX = 44
/** A 1280 px window at 200% zoom lays out like a 640 px one. */
const ZOOMED = { width: 640, height: 400 }
/** More than any screen has; the walk fails if the focus neither leaves the page nor comes round again by then. */
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

type TabStop = { element: string; ring: boolean } | 'left' | 'again'

/**
 * Compares the focused element's visible outline and shadows with its look after a blur, then focuses it again so the
 * next Tab moves on from it. Returns 'left' when the focus has left the page and 'again' when it comes back to an
 * element it already visited.
 */
function focusLook(): TabStop {
  const element = document.activeElement
  if (!(element instanceof HTMLElement) || element === document.body) return 'left'
  const visited = ((window as { tabStops?: WeakSet<Element> }).tabStops ??= new WeakSet())
  if (visited.has(element)) return 'again'
  visited.add(element)
  const clear = (color: string) => color === 'transparent' || /^rgba\(.*,\s*0\)$|\/\s*0\)$/.test(color)
  // Only what draws: an outline with a style, a width and a colour, and shadows that are neither clear nor empty.
  const look = () => {
    const style = getComputedStyle(element)
    const outline = style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth) > 0 && !clear(style.outlineColor)
      ? `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor}`
      : ''
    const shadows = style.boxShadow === 'none'
      ? []
      : style.boxShadow.split(/,(?![^(]*\))/).map((shadow) => shadow.trim())
          .filter((shadow) => !/ 0px 0px 0px 0px$/.test(shadow) && !clear(shadow.replace(/\s[-\d.]+px.*$/, '')))
    return `${outline} | ${shadows.join(', ')}`
  }
  const focused = look()
  element.blur()
  const unfocused = look()
  element.focus()
  return { element: element.outerHTML.slice(0, 80), ring: focused !== unfocused }
}

for (const screen of SCREENS) {
  test(`${screen.name} passes axe, fits the width and has 44 px targets`, async ({ page }) => {
    await screen.reach(page)
    // The layout checks run on the paused clock, on the screen exactly as reached.
    await expectNoSidewaysScroll(page)
    await expectTargetSize(page)
    // axe resolves each rule on a timer, which the paused clock would hold back, so the countdown runs during the scan;
    // the scan must end before it runs out, or it would have checked the time-up state instead of the screen.
    await page.clock.resume()
    await expectAccessible(page)
    await expect(page.getByTestId('time-up')).toHaveCount(0)
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
    let checked = 0
    for (; checked < MAX_TAB_STOPS; checked += 1) {
      await page.keyboard.press('Tab')
      const stop = await page.evaluate(focusLook)
      if (typeof stop === 'string') break
      expect(stop.ring, stop.element).toBe(true)
    }
    expect(checked, `the focus walk stopped after ${MAX_TAB_STOPS} Tab stops`).toBeLessThan(MAX_TAB_STOPS)
    expect(checked).toBeGreaterThan(0)
  })
}
