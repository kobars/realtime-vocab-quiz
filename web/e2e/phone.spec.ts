// AI-ASSISTED: on a phone the quiz and the leaderboard are tabs that the keyboard switches, the open question's time left stays in the header, and a long name never scrolls the page sideways.
import { expect, type Page, test } from '@playwright/test'
import { strings } from '../src/strings'
import { join, OPEN_QUIZ, uniqueName } from './stack'

async function expectNoSidewaysScroll(page: Page): Promise<void> {
  const { scrollWidth, clientWidth } = await page.evaluate(() => {
    const { scrollWidth, clientWidth } = document.documentElement
    return { scrollWidth, clientWidth }
  })
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth)
}

test('the tabs switch with the keyboard, the time left leads back to the question, and a long name fits', async ({ page }) => {
  const name = uniqueName('W'.repeat(23)) // 32 characters, the longest name, in the widest letter
  await join(page, OPEN_QUIZ, name)
  const quiz = page.getByRole('tab', { name: strings.quiz.tab })
  const board = page.getByRole('tab', { name: strings.leaderboard.title })
  await expect(quiz).toHaveAttribute('aria-selected', 'true')

  await quiz.focus()
  await page.keyboard.press('ArrowRight')
  await expect(board).toBeFocused()
  await expect(board).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('li[aria-current="true"]')).toContainText(name)
  await expectNoSidewaysScroll(page)

  await page.keyboard.press('Home')
  await expect(quiz).toBeFocused()
  await page.getByTestId('start').click()
  await expect(page.getByTestId('progress')).toBeVisible()
  await quiz.focus()
  await page.keyboard.press('End')
  await expect(board).toHaveAttribute('aria-selected', 'true')
  const left = page.getByTestId('time-left')
  await expect(left).toHaveText(/\b\d+ s left$/)
  await expectNoSidewaysScroll(page)
  await left.click()
  await expect(quiz).toBeFocused()
  await expect(page.locator('[data-choice="0"]')).toBeVisible()
  await expectNoSidewaysScroll(page)
})
