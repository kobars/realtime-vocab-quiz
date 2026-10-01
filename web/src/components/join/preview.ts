// AI-ASSISTED: the quiz preview on the join screen: `GET /quizzes/{id}` read into a found, not-found or unavailable result.

export interface QuizPreview {
  title: string
  questionCount: number
  status: 'open' | 'ended'
  playerCount: number
}

export type PreviewResult = { kind: 'found'; quiz: QuizPreview } | { kind: 'not-found' } | { kind: 'unavailable' }

function toPreview(value: unknown): QuizPreview | null {
  if (typeof value !== 'object' || value === null) return null
  const { title, questionCount, status, playerCount } = value as Record<string, unknown>
  const valid =
    typeof title === 'string' &&
    Number.isInteger(questionCount) &&
    (status === 'open' || status === 'ended') &&
    Number.isInteger(playerCount)
  return valid ? { title, questionCount: questionCount as number, status, playerCount: playerCount as number } : null
}

/**
 * The preview is a convenience: a failed request is `unavailable` and the join goes ahead, so the
 * WebSocket `join` stays the authority on whether the quiz exists. Only a 404 means "no such quiz".
 */
export async function fetchQuizPreview(
  quizId: string,
  fetchFn: (url: string) => Promise<Response> = (url) => fetch(url),
  base = '/api',
): Promise<PreviewResult> {
  try {
    const response = await fetchFn(`${base}/quizzes/${encodeURIComponent(quizId)}`)
    if (response.status === 404) return { kind: 'not-found' }
    const quiz = response.ok ? toPreview(await response.json()) : null
    return quiz === null ? { kind: 'unavailable' } : { kind: 'found', quiz }
  } catch {
    return { kind: 'unavailable' }
  }
}
