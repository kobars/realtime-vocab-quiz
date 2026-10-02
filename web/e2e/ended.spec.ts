// AI-ASSISTED: an ended quiz, opened from its share link, shows its final results and nothing to answer.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { ENDED_QUIZ, expectAccessible, uniqueName } from './stack'

test('an ended quiz opens read-only on its final results', async ({ page }) => {
  await page.goto(`/q/${ENDED_QUIZ}`)
  await expect(page.getByLabel(strings.join.quizIdLabel)).toHaveValue(ENDED_QUIZ)
  await expect(page.getByText(strings.join.ended)).toBeVisible()
  await page.getByLabel(strings.join.nameLabel).fill(uniqueName('Eve'))
  await expectAccessible(page)

  await page.getByRole('button', { name: strings.join.submitEnded }).click()
  await expect(page.getByRole('heading', { name: strings.results.title })).toBeVisible()
  await expect(page.getByTestId('start')).toHaveCount(0)
  await expect(page.locator('[data-choice]')).toHaveCount(0)
  await expectAccessible(page)
})
