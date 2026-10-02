// AI-ASSISTED: a visitor hosts a quiz from the join screen, a player joins it from the host's link in another browser, and the host ends it.
import { expect, test } from '@playwright/test'
import { strings } from '../src/strings'
import { expectAccessible, uniqueName } from './stack'

/** The host page reads the player count every 3 s. */
const POLLED = { timeout: 10_000 }

test('a visitor hosts a quiz, a player joins from its link and the host ends it', async ({ page, browser }) => {
  await page.goto('/')
  await page.getByRole('link', { name: strings.join.host }).click()
  await expect(page).toHaveURL('/host')
  await page.locator('[data-bank]').first().click()

  const quizId = (await page.getByTestId('host-quiz-id').textContent())?.trim() ?? ''
  expect(quizId).toMatch(/^[A-Z0-9-]{3,16}$/)
  await expect(page.getByTestId('players')).toHaveText(strings.host.players(0), POLLED)
  await expectAccessible(page)

  // Another browser context: its own tab storage and session, like a phone that scanned the QR code.
  const playerContext = await browser.newContext()
  const player = await playerContext.newPage()
  await player.goto(await page.locator('#share-link').inputValue())
  await expect(player.getByLabel(strings.join.quizIdLabel)).toHaveValue(quizId)
  await player.getByLabel(strings.join.nameLabel).fill(uniqueName('Ana'))
  await player.getByRole('button', { name: strings.join.submit }).click()
  await expect(player).toHaveURL(`/quiz/${quizId}`)
  await expect(page.getByTestId('players')).toHaveText(strings.host.players(1), POLLED)

  // A refresh keeps the host controls: the host token is in the tab's sessionStorage.
  await page.reload()
  await expect(page.getByTestId('host-quiz-id')).toHaveText(quizId)

  await page.getByRole('button', { name: strings.host.end }).click()
  await page.getByRole('button', { name: strings.host.confirm }).click()
  await expect(page.getByRole('heading', { name: strings.host.ended(quizId) })).toBeFocused()
  await expect(player.getByRole('heading', { name: strings.results.title })).toBeVisible()
  await expectAccessible(page)
  await playerContext.close()
})
