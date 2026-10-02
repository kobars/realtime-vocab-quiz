// AI-ASSISTED: before the browser specs, the MOCK admin API starts the open quiz and ends the other one.
import process from 'node:process'
import { request } from '@playwright/test'
import { ENDED_QUIZ, OPEN_QUIZ, STACK_URL } from './stack'

const WINDOW_MS = 50 * 60_000 // a rerun against the same stack within this time reuses the open quiz
const CONFLICT = 409 // the quiz exists

export default async function globalSetup(): Promise<void> {
  const token = process.env.ADMIN_TOKEN
  if (!token) throw new Error('set ADMIN_TOKEN, as the stack has it')
  const api = await request.newContext({ baseURL: `${STACK_URL}/api/`, extraHTTPHeaders: { 'X-Admin-Token': token } })
  try {
    for (const quizId of [OPEN_QUIZ, ENDED_QUIZ]) {
      const created = await api.post('admin/quizzes', { data: { quizId, windowMs: WINDOW_MS } })
      if (!created.ok() && created.status() !== CONFLICT) throw new Error(`create ${quizId}: HTTP ${created.status()}`)
    }
    const info = await api.get(`quizzes/${OPEN_QUIZ}`)
    if ((await info.json()).status !== 'open') throw new Error(`quiz ${OPEN_QUIZ} has ended: recreate the stack`)
    const ended = await api.post(`admin/quizzes/${ENDED_QUIZ}/end`)
    if (!ended.ok()) throw new Error(`end ${ENDED_QUIZ}: HTTP ${ended.status()}`)
  } finally {
    await api.dispose()
  }
}
