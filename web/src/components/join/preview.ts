// AI-ASSISTED: the quiz preview on the join screen: `GET /quizzes/{id}` read into a found, not-found or unavailable result.

export interface QuizPreview {
  title: string
  questionCount: number
  status: 'open' | 'ended'
  players: number
}

export type PreviewResult = { kind: 'found'; quiz: QuizPreview } | { kind: 'not-found' } | { kind: 'unavailable' }

function toPreview(value: unknown): QuizPreview | null {
  if (typeof value !== 'object' || value === null) return null
  const { title, questionCount, status, players } = value as Record<string, unknown>
  const valid =
    typeof title === 'string' &&
    Number.isInteger(questionCount) &&
    (status === 'open' || status === 'ended') &&
    Number.isInteger(players)
  return valid ? { title, questionCount: questionCount as number, status, players: players as number } : null
}

/** How long the lookup may take, headers and body together, before the join goes ahead without it. */
export const PREVIEW_TIMEOUT_MS = 3_000

type FetchFn = (url: string, init: RequestInit) => Promise<Response>

/** Only the endpoint's own 404 names the quiz as missing; a 404 from a missing route or a proxy does not. */
async function isQuizNotFound(response: Response): Promise<boolean> {
  const body: unknown = await response.json().catch(() => null)
  return typeof body === 'object' && body !== null && (body as Record<string, unknown>).error === 'QUIZ_NOT_FOUND'
}

async function lookUp(url: string, fetchFn: FetchFn, signal: AbortSignal): Promise<PreviewResult> {
  const response = await fetchFn(url, { signal })
  if (response.status === 404) return (await isQuizNotFound(response)) ? { kind: 'not-found' } : { kind: 'unavailable' }
  const quiz = response.ok ? toPreview(await response.json()) : null
  return quiz === null ? { kind: 'unavailable' } : { kind: 'found', quiz }
}

/**
 * The preview is a convenience: a failed or slow request is `unavailable` and the join goes ahead, so the
 * WebSocket `join` stays the authority on whether the quiz exists. Only a `QUIZ_NOT_FOUND` 404 means "no such quiz".
 */
export async function fetchQuizPreview(
  quizId: string,
  fetchFn: FetchFn = (url, init) => fetch(url, init),
  base = '/api',
  timeoutMs = PREVIEW_TIMEOUT_MS,
): Promise<PreviewResult> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  // The timer wins even when the request ignores the abort signal.
  const timedOut = new Promise<PreviewResult>((resolve) => {
    timer = setTimeout(() => {
      controller.abort()
      resolve({ kind: 'unavailable' })
    }, timeoutMs)
  })
  const looked = lookUp(`${base}/quizzes/${encodeURIComponent(quizId)}`, fetchFn, controller.signal)
    .catch((): PreviewResult => ({ kind: 'unavailable' }))
  try {
    return await Promise.race([looked, timedOut])
  } finally {
    clearTimeout(timer)
  }
}
