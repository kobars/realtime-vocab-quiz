// AI-ASSISTED: a mocked backend for the visual and accessibility specs: the HTTP calls, a scripted WebSocket server and a paused clock.
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

/** Serves the join screen's quiz preview, the mock identity and a quiz socket that answers each request. */
export async function mockBackend(page: Page, scenario: Scenario = {}): Promise<void> {
  await page.clock.install({ time: START })
  await page.clock.pauseAt(START.getTime() + 1_000)
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
