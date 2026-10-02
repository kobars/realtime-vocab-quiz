// AI-ASSISTED: two players in two browser contexts: one scores, the other's leaderboard shows it live.
import { expect, test } from '@playwright/test'
import { answerKey, join, OPEN_QUIZ, uniqueName } from './stack'

test("another player's score reaches my leaderboard live", async ({ browser }) => {
  const [watching, scoring] = await Promise.all([browser.newContext(), browser.newContext()])
  try {
    const [watcher, scorer] = await Promise.all([watching.newPage(), scoring.newPage()])
    const name = uniqueName('Cy')
    await join(watcher, OPEN_QUIZ, uniqueName('Dee'))
    await join(scorer, OPEN_QUIZ, name)
    const score = watcher.getByRole('listitem').filter({ hasText: name }).locator('span').last()
    await expect(score).toHaveText('0') // the join is on the board before any score

    await scorer.getByTestId('start').click()
    await scorer.locator(`[data-choice="${answerKey(OPEN_QUIZ)[0]}"]`).click()
    await expect(score).toHaveText(/^1[0-5]\d$/)
  } finally {
    await Promise.all([watching.close(), scoring.close()])
  }
})
