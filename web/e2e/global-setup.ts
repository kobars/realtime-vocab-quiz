// AI-ASSISTED: before the browser specs, the MOCK admin API starts the open quizzes and ends the other one.
import process from 'node:process'
import { request } from '@playwright/test'
import { CROWDED_BANK, CROWDED_QUIZ, ENDED_QUIZ, OPEN_QUIZ, STACK_URL } from './stack'

const CONFLICT = 409 // the quiz exists

export default async function globalSetup(): Promise<void> {
  const token = process.env.ADMIN_TOKEN
  if (!token) throw new Error('set ADMIN_TOKEN, as the stack has it')
  const api = await request.newContext({ baseURL: `${STACK_URL}/api/`, extraHTTPHeaders: { 'X-Admin-Token': token } })
  try {
    // An earlier run's quiz keeps its players and its window for 24 h: the specs need new ones.
    const restart = '`docker compose --profile full down -v`, then `up -d --wait`'
    const opened = async (quizId: string, bankQuizId?: string): Promise<void> => {
      const created = await api.post('admin/quizzes', { data: { quizId, bankQuizId } })
      if (created.status() === CONFLICT) throw new Error(`quiz ${quizId} exists from an earlier run: start the stack afresh: ${restart}`)
      if (!created.ok()) throw new Error(`create ${quizId}: HTTP ${created.status()}`)
    }
    await opened(OPEN_QUIZ)
    const created = await api.post('admin/quizzes', { data: { quizId: ENDED_QUIZ } })
    if (!created.ok() && created.status() !== CONFLICT) throw new Error(`create ${ENDED_QUIZ}: HTTP ${created.status()}`)
    const ended = await api.post(`admin/quizzes/${ENDED_QUIZ}/end`)
    if (!ended.ok()) throw new Error(`end ${ENDED_QUIZ}: HTTP ${ended.status()}`)
    // The spec on it counts its players exactly, so it must start empty.
    await opened(CROWDED_QUIZ, CROWDED_BANK)
  } finally {
    await api.dispose()
  }
}
