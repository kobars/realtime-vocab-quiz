// AI-ASSISTED: before the browser specs, the MOCK admin API starts the open quiz and ends the other one.
import process from 'node:process'
import { request } from '@playwright/test'
import { ENDED_QUIZ, OPEN_QUIZ, STACK_URL } from './stack'

const CONFLICT = 409 // the quiz exists

export default async function globalSetup(): Promise<void> {
  const token = process.env.ADMIN_TOKEN
  if (!token) throw new Error('set ADMIN_TOKEN, as the stack has it')
  const api = await request.newContext({ baseURL: `${STACK_URL}/api/`, extraHTTPHeaders: { 'X-Admin-Token': token } })
  try {
    // An earlier run's quiz keeps its players and its window for 24 h: the specs need a new one.
    const open = await api.post('admin/quizzes', { data: { quizId: OPEN_QUIZ } })
    if (open.status() === CONFLICT) {
      const restart = '`docker compose --profile full down -v`, then `up -d --wait`'
      throw new Error(`quiz ${OPEN_QUIZ} exists from an earlier run: start the stack afresh: ${restart}`)
    }
    if (!open.ok()) throw new Error(`create ${OPEN_QUIZ}: HTTP ${open.status()}`)
    const created = await api.post('admin/quizzes', { data: { quizId: ENDED_QUIZ } })
    if (!created.ok() && created.status() !== CONFLICT) throw new Error(`create ${ENDED_QUIZ}: HTTP ${created.status()}`)
    const ended = await api.post(`admin/quizzes/${ENDED_QUIZ}/end`)
    if (!ended.ok()) throw new Error(`end ${ENDED_QUIZ}: HTTP ${ended.status()}`)
  } finally {
    await api.dispose()
  }
}
