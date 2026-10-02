// AI-ASSISTED: shared helpers of the browser specs: the stack's URL, its quizzes, the join, the answer key and the axe scan.
import { readFileSync } from 'node:fs'
import process from 'node:process'
import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'
import { strings } from '../src/strings'

/** The full stack's nginx; `make test-browser` passes the Makefile's STACK_URL. */
export const STACK_URL = (process.env.STACK_URL ?? 'http://localhost:8080').replace(/\/$/, '')
/** The component gallery's preview server in the visual and accessibility suite (`make ui-check` runs it in a container). */
export const GALLERY_URL = 'http://127.0.0.1:4174'
/** Open for the whole run (global setup starts it), and one the setup has ended. */
export const OPEN_QUIZ = 'VOCAB-42'
export const ENDED_QUIZ = 'ACAD-10'
/**
 * Also open for the whole run, a run of the `VOCAB-42` bank under its own ID: the spec that needs more players than the
 * top 10 fills it, and the other specs' boards stay short. The system tests keep `BIZ-20`; the run codes of the hosting
 * API and `make demo` (four characters, no O) never make this ID.
 */
export const CROWDED_QUIZ = 'VOCAB-42-CROWD'
export const CROWDED_BANK = 'VOCAB-42'

/** The index of the correct choice of each question of a quiz, from the API's mock question bank. */
export function answerKey(quizId: string): number[] {
  const file = new URL(`../../api/src/quiz/adapters/mock_questions/data/${quizId.toLowerCase()}.json`, import.meta.url)
  const quiz = JSON.parse(readFileSync(file, 'utf8')) as { questions: { answer: number }[] }
  return quiz.questions.map((question) => question.answer)
}

/** A display name no earlier run on the same stack has used. */
export const uniqueName = (prefix: string): string => `${prefix}-${crypto.randomUUID().slice(0, 8)}`

/** Joins from the start screen and waits for the quiz screen. */
export async function join(page: Page, quizId: string, name: string): Promise<void> {
  await page.goto('/')
  await page.getByLabel(strings.join.quizIdLabel).fill(quizId)
  await page.getByLabel(strings.join.nameLabel).fill(name)
  await page.getByRole('button', { name: strings.join.submit }).click()
  await expect(page).toHaveURL(`/quiz/${quizId}`)
}

/** No WCAG 2.2 A or AA rule (colour contrast included) fails on the page as it is now. */
export async function expectAccessible(page: Page): Promise<void> {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  expect(violations.map((rule) => `${rule.id}: ${rule.nodes.map((node) => node.target.join(' ')).join(', ')}`)).toEqual([])
}
