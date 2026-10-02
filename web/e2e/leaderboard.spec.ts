// AI-ASSISTED: two players in two browser contexts: one scores, the other's leaderboard shows it live; and with more than 10 players the board shows the top 10, the first player in place and the last one pinned under them, and "Show all players" lists each player once.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { answerKey, CROWDED_QUIZ, join, OPEN_QUIZ, uniqueName } from './stack'

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

test('with more than 10 players the board shows the top 10, and "Show all players" lists each player once', async ({ browser }) => {
  test.setTimeout(90_000)
  const context = await browser.newContext()
  try {
    // Each tab of one context is a player of its own (the identity lives in the tab's sessionStorage).
    const others = Array.from({ length: 10 }, () => uniqueName('Gus'))
    const firstPage = await context.newPage()
    await join(firstPage, CROWDED_QUIZ, others[0] ?? '')
    for (const name of others.slice(1)) await join(await context.newPage(), CROWDED_QUIZ, name)
    const name = uniqueName('Gus')
    const page = await context.newPage()
    await join(page, CROWDED_QUIZ, name)
    // With no score yet, the earlier join ranks first: the first player is #1 in place, the last one #11, pinned.
    const first = firstPage.getByRole('region', { name: strings.leaderboard.title })
    await expect(first.locator('[aria-current="true"]')).toContainText(`#1${others[0] ?? ''}`)
    await expect(first.getByTestId('pinned')).toHaveCount(0)
    const board = page.getByRole('region', { name: strings.leaderboard.title })
    await expect(board.getByRole('listitem')).toHaveCount(10)
    await expect(board.getByTestId('pinned')).toContainText(`#11${name}`)
    await expect(board.getByRole('listitem').filter({ hasText: name })).toHaveCount(0)
    await board.getByRole('button', { name: strings.leaderboard.showAll }).click()
    await expect(board.getByTestId('page-range')).toHaveText(strings.leaderboard.range(1, 11, 11))
    for (const player of [...others, name]) await expect(board.getByRole('listitem').filter({ hasText: player })).toHaveCount(1)
  } finally {
    await context.close()
  }
})
