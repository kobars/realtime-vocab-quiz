// AI-ASSISTED: a player answers every question of the quiz and reaches the finished screen with the total.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { answerKey, expectAccessible, join, OPEN_QUIZ, uniqueName } from './stack'

test('a player answers every question and reaches the results', async ({ page }) => {
  const key = answerKey(OPEN_QUIZ)
  await join(page, OPEN_QUIZ, uniqueName('Flo'))
  await page.getByTestId('start').click()
  for (const [i, correct] of key.entries()) {
    await expect(page.getByTestId('progress')).toHaveText(strings.quiz.progress(i + 1, key.length))
    await page.locator(`[data-choice="${correct}"]`).click()
    await expect(page.getByTestId('points')).toContainText(/\+1[0-5]\d points/)
    const last = i === key.length - 1
    await page.getByRole('button', { name: last ? strings.quiz.seeResult : strings.quiz.nextQuestion }).click()
  }
  await expect(page.getByRole('heading', { name: strings.results.finished })).toBeFocused()
  // Every answer was correct and on time: 100–150 points each, in the result and, once counted up, in the header.
  const total = Number((await page.getByTestId('my-result').textContent())?.match(/(\d+) points/)?.[1])
  expect(total).toBeGreaterThanOrEqual(100 * key.length)
  expect(total).toBeLessThanOrEqual(150 * key.length)
  await expect(page.getByTestId('score')).toHaveText(strings.quiz.score(total))
  await expectAccessible(page)
})
