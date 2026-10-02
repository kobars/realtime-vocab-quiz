// AI-ASSISTED: every screen the visual and accessibility specs check, each reached on the mocked backend.
import { expect, type Page, test } from '@playwright/test'
import { strings } from '../../src/strings'
import { CORRECT, ME, QUESTION_COUNT, QUIZ_ID } from './frames'
import { HOSTED_ID, HOSTED_PLAYERS, mockBackend, type Scenario } from './server'

export interface Screen {
  name: string
  reach: (page: Page) => Promise<void>
}

/** Tailwind's `lg` breakpoint: from here the leaderboard sits beside the quiz instead of in a tab. */
const WIDE_PX = 1024

async function joinQuiz(page: Page, scenario: Scenario = {}): Promise<void> {
  await mockBackend(page, scenario)
  await page.goto(`/?quiz=${QUIZ_ID}`)
  await page.getByLabel(strings.join.nameLabel).fill(ME.displayName)
  await page.getByRole('button', { name: strings.join.submit }).click()
  await expect(page).toHaveURL(`/quiz/${QUIZ_ID}`)
}

async function intro(page: Page): Promise<void> {
  await joinQuiz(page)
  await expect(page.getByTestId('start')).toBeFocused()
}

async function openQuestion(page: Page): Promise<void> {
  await intro(page)
  await page.getByTestId('start').click()
  await expect(page.getByTestId('progress')).toHaveText(strings.quiz.progress(1, QUESTION_COUNT))
}

async function answer(page: Page, choice: number): Promise<void> {
  await openQuestion(page)
  await page.locator(`[data-choice="${choice}"]`).click()
  await expect(page.getByTestId('feedback')).toBeVisible()
}

async function hostQuiz(page: Page): Promise<void> {
  await mockBackend(page)
  await page.goto('/host')
  await page.locator('[data-bank="VOCAB-42"]').click()
  await expect(page.getByTestId('players')).toHaveText(strings.host.players(HOSTED_PLAYERS))
}

export const SCREENS: Screen[] = [
  {
    name: 'join',
    reach: async (page) => {
      await mockBackend(page)
      await page.goto('/')
      await expect(page.getByLabel(strings.join.quizIdLabel)).toBeFocused()
    },
  },
  {
    name: 'join-error',
    reach: async (page) => {
      await mockBackend(page)
      await page.goto('/')
      await page.getByLabel(strings.join.quizIdLabel).press('Enter') // submits the empty form
      await expect(page.getByText(strings.join.nameRequired)).toBeVisible()
    },
  },
  { name: 'intro', reach: intro },
  { name: 'question', reach: openQuestion },
  {
    name: 'last-5s',
    reach: async (page) => {
      await openQuestion(page)
      // 15.5 s, so the last animation frame falls inside the fifth second whatever the frame times.
      await page.clock.runFor(15_500)
      await expect(page.getByTestId('ring')).toHaveAccessibleName(strings.quiz.secondsLeft(5))
    },
  },
  { name: 'feedback-correct', reach: (page) => answer(page, CORRECT) },
  { name: 'feedback-wrong', reach: (page) => answer(page, (CORRECT + 1) % 4) },
  {
    // Phones and tablets: the Leaderboard tab. On a desktop the leaderboard sits beside every play screen above, so this
    // screen would be the intro again.
    name: 'leaderboard',
    reach: async (page) => {
      test.skip((page.viewportSize()?.width ?? 0) >= WIDE_PX, 'the play screens already show the leaderboard column')
      await intro(page)
      await page.getByRole('tab', { name: strings.leaderboard.title }).click()
      await expect(page.getByTestId('pinned')).toBeVisible()
    },
  },
  {
    name: 'finished',
    reach: async (page) => {
      await joinQuiz(page, { finished: true })
      await expect(page.getByRole('heading', { name: strings.results.finished })).toBeFocused()
    },
  },
  {
    name: 'results',
    reach: async (page) => {
      await joinQuiz(page, { ended: true })
      await expect(page.getByRole('heading', { name: strings.results.title })).toBeFocused()
    },
  },
  {
    name: 'host',
    reach: async (page) => {
      await mockBackend(page)
      await page.goto('/host')
      await expect(page.locator('[data-bank]')).toHaveCount(3)
    },
  },
  {
    name: 'host-created',
    reach: async (page) => {
      await hostQuiz(page)
      await expect(page.getByTestId('host-quiz-id')).toHaveText(HOSTED_ID)
    },
  },
  {
    name: 'host-confirm',
    reach: async (page) => {
      await hostQuiz(page)
      await page.getByTestId('end').click()
      await expect(page.getByTestId('keep-open')).toBeFocused()
      // The click leaves the pointer over the box that replaced the button, and the focus scrolled it into view.
      await page.mouse.move(0, 0)
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: 'host-ended',
    reach: async (page) => {
      await hostQuiz(page)
      await page.getByTestId('end').click()
      await page.getByTestId('confirm').click()
      await expect(page.getByRole('heading', { name: strings.host.ended(HOSTED_ID) })).toBeFocused()
    },
  },
  {
    name: 'not-found',
    reach: async (page) => {
      await mockBackend(page)
      await page.goto('/no-such-page')
      await expect(page.getByRole('heading', { name: strings.notFound.title })).toBeVisible()
    },
  },
]
