// AI-ASSISTED: a player finds a quiz by its ID, sees its preview and joins it.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { expectAccessible, OPEN_QUIZ, uniqueName } from './stack'

test('a player joins a quiz by its ID', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel(strings.join.quizIdLabel).fill(OPEN_QUIZ)
  await page.getByLabel(strings.join.nameLabel).fill(uniqueName('Ana')) // leaving the ID looks it up
  await expect(page.getByText(strings.join.preview.open, { exact: true })).toBeVisible()
  await expectAccessible(page)

  await page.getByRole('button', { name: strings.join.submit }).click()
  await expect(page).toHaveURL(`/quiz/${OPEN_QUIZ}`)
  await expect(page.getByRole('heading', { name: strings.quiz.title(OPEN_QUIZ) })).toBeVisible()
  await expect(page.getByTestId('start')).toHaveText(strings.quiz.start)
  await expectAccessible(page)
})
