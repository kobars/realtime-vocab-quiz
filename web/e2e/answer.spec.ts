// AI-ASSISTED: a player answers the first question correctly and sees the points, the score and their leaderboard row.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { answerKey, expectAccessible, join, OPEN_QUIZ, uniqueName } from './stack'

test('a correct answer scores and shows on my leaderboard row', async ({ page }) => {
  const name = uniqueName('Ben')
  await join(page, OPEN_QUIZ, name)
  await page.getByTestId('start').click()
  await expect(page.getByTestId('progress')).toHaveText(strings.quiz.progress(1, answerKey(OPEN_QUIZ).length))
  await expectAccessible(page)

  await page.locator(`[data-choice="${answerKey(OPEN_QUIZ)[0]}"]`).click()
  await expect(page.getByTestId('points')).toContainText(/\+1[0-5]\d points/)
  await expect(page.getByTestId('score')).toHaveText(/^Score 1[0-5]\d$/)
  const mine = page.locator('li[aria-current="true"]')
  await expect(mine).toContainText(`${name} ${strings.leaderboard.you}`)
  await expect(mine.locator('span').last()).toHaveText(/^1[0-5]\d$/)
  await expectAccessible(page)
})
