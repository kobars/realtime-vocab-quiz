// AI-ASSISTED: a mocked backend for the visual and accessibility specs: the HTTP calls (hosting included), a scripted WebSocket server and a paused clock.
import type { Page } from '@playwright/test'
import type { ClientMessage, ServerMessage } from '../../src/protocol/types.generated'
import { answerResult, joined, ME, QUESTION_COUNT, QUIZ_ID, question, snapshot } from './frames'

export interface Scenario {
  /** The player answered every question: the join lands on the finished screen. */
  finished?: boolean
  /** The quiz has ended: the resync after the join returns the final standings. */
  ended?: boolean
}

/** The fake clock's start; it stays paused, so countdowns only move when a spec runs the clock. */
const START = new Date('2026-10-01T09:00:00Z')
/** The quiz the host screens create, in the hosting API's shapes. */
export const HOSTED_ID = 'VOCAB-42-7K3Q'
export const HOSTED_PLAYERS = 12
const BANKS = [
  { id: 'VOCAB-42', title: 'Everyday English', questionCount: 10 },
  { id: 'ACAD-10', title: 'Academic words', questionCount: 10 },
  { id: 'BIZ-20', title: 'Business English', questionCount: 10 },
]
const CREATED = { quizId: HOSTED_ID, sharePath: `/q/${HOSTED_ID}`, hostToken: 'host-token', windowMs: 1_800_000, endsAtMs: START.getTime() + 1_800_000 }

/** The bank list, the create, the hosted quiz's preview and its end. */
async function mockHosting(page: Page): Promise<void> {
  await page.route('**/api/banks', (route) => route.fulfill({ json: BANKS }))
  await page.route('**/api/quizzes', (route) => route.fulfill({ status: 201, json: CREATED }))
  await page.route(`**/api/quizzes/${HOSTED_ID}`, (route) =>
    route.fulfill({ json: { title: BANKS[0]?.title, questionCount: 10, status: 'open', players: HOSTED_PLAYERS } }),
  )
  await page.route(`**/api/quizzes/${HOSTED_ID}/end`, (route) =>
    route.fulfill({ json: { quizId: HOSTED_ID, status: 'ended', endSeq: 1 } }),
  )
}

function reply(message: ClientMessage, scenario: Scenario): ServerMessage | null {
  switch (message.type) {
    case 'join':
      return joined(scenario.finished ?? false)
    case 'resync':
      return snapshot(scenario.ended ? 'ended' : 'open')
    case 'next':
      return message.questionIndex < QUESTION_COUNT ? question(message.questionIndex) : null
    case 'answer':
      return answerResult(message.questionIndex, message.choiceIndex, message.submissionId)
    case 'ping':
    case 'get_leaderboard':
      return null
  }
}

/** Serves the join screen's quiz preview, hosting, the mock identity and a quiz socket that answers each request. */
export async function mockBackend(page: Page, scenario: Scenario = {}): Promise<void> {
  await page.clock.install({ time: START })
  await page.clock.pauseAt(START.getTime() + 1_000)
  await mockHosting(page)
  await page.route(`**/api/quizzes/${QUIZ_ID}`, (route) =>
    route.fulfill({ json: { title: 'Everyday adjectives', questionCount: QUESTION_COUNT, status: 'open', players: 250 } }),
  )
  await page.route('**/api/sessions', (route) => route.fulfill({ json: { userId: ME.userId, sessionToken: 'session' } }))
  await page.route('**/api/tickets', (route) => route.fulfill({ json: { ticket: 'ticket' } }))
  await page.routeWebSocket('**/ws?ticket=*', (socket) => {
    socket.onMessage((raw) => {
      const answer = reply(JSON.parse(String(raw)) as ClientMessage, scenario)
      if (answer !== null) socket.send(JSON.stringify(answer))
    })
  })
}
