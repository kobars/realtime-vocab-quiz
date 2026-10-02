// AI-ASSISTED: the self-service hosting calls (the bank list, creating a quiz, ending it) read into results the host page can show, and the hosted quiz kept in the tab's sessionStorage.
import { withTimeout } from '@/lib/timeout'

export interface Bank {
  id: string
  title: string
  questionCount: number
}

export interface HostedQuiz {
  quizId: string
  sharePath: string
  hostToken: string
  endsAtMs: number
}

export type BanksResult = { kind: 'ok'; banks: Bank[] } | { kind: 'off' } | { kind: 'error' }
export type CreateResult =
  | { kind: 'created'; quiz: HostedQuiz }
  | { kind: 'rate-limited'; retryAfterS: number }
  | { kind: 'full' }
  | { kind: 'off' }
  | { kind: 'invalid' }
  | { kind: 'error' }
/** `gone`: the quiz has already ended or no longer exists, so there is nothing left to end. */
export type EndResult = { kind: 'ended' } | { kind: 'gone' } | { kind: 'forbidden' } | { kind: 'error' }

/** How long a hosting call may take, headers and body together. */
export const HOSTING_TIMEOUT_MS = 8_000
/** How often the host page reads the player count while it is visible. */
export const POLL_MS = 3_000
/** The wait shown after a 429 without a usable `Retry-After`. */
export const DEFAULT_RETRY_AFTER_S = 60
export const HOST_KEY = 'quiz.host'

type FetchFn = (url: string, init: RequestInit) => Promise<Response>
const send: FetchFn = (url, init) => fetch(url, init)

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null
const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value !== ''

function toBank(value: unknown): Bank | null {
  if (!isRecord(value)) return null
  const { id, title, questionCount } = value
  return nonEmpty(id) && nonEmpty(title) && Number.isInteger(questionCount) ? { id, title, questionCount: questionCount as number } : null
}

function toHostedQuiz(value: unknown): HostedQuiz | null {
  if (!isRecord(value)) return null
  const { quizId, sharePath, hostToken, endsAtMs } = value
  const valid = nonEmpty(quizId) && nonEmpty(sharePath) && sharePath.startsWith('/') && nonEmpty(hostToken) && Number.isFinite(endsAtMs)
  return valid ? { quizId, sharePath, hostToken, endsAtMs: endsAtMs as number } : null
}

async function errorCode(response: Response): Promise<string | null> {
  const body: unknown = await response.json().catch(() => null)
  return isRecord(body) && typeof body.error === 'string' ? body.error : null
}

/** Runs one call with the deadline; a failed, slow or unreadable call is `error`. */
function call<T>(request: (signal: AbortSignal) => Promise<T | { kind: 'error' }>): Promise<T | { kind: 'error' }> {
  return withTimeout(HOSTING_TIMEOUT_MS, request).catch(() => ({ kind: 'error' as const }))
}

/** The bank quizzes a visitor may host; a 404, or an empty list, means the server offers no public hosting. */
export function fetchBanks(fetchFn = send, base = '/api'): Promise<BanksResult> {
  return call(async (signal) => {
    const response = await fetchFn(`${base}/banks`, { signal })
    if (response.status === 404) return { kind: 'off' }
    const body: unknown = response.ok ? await response.json() : null
    if (Array.isArray(body) && body.length === 0) return { kind: 'off' }
    const banks = Array.isArray(body) ? body.map(toBank) : []
    return banks.length > 0 && banks.every((bank) => bank !== null) ? { kind: 'ok', banks: banks as Bank[] } : { kind: 'error' }
  })
}

/** `Retry-After` in seconds (the API sends delta seconds), at least 1. */
function retryAfter(response: Response): number {
  const seconds = Number(response.headers.get('Retry-After'))
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : DEFAULT_RETRY_AFTER_S
}

export function createQuiz(bankQuizId: string, fetchFn = send, base = '/api'): Promise<CreateResult> {
  return call(async (signal) => {
    const response = await fetchFn(`${base}/quizzes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bankQuizId }),
      signal,
    })
    if (response.status === 201) {
      const quiz = toHostedQuiz(await response.json())
      return quiz === null ? { kind: 'error' } : { kind: 'created', quiz }
    }
    if (response.status === 429) return { kind: 'rate-limited', retryAfterS: retryAfter(response) }
    if (response.status === 404) return { kind: 'off' }
    const code = await errorCode(response)
    if (response.status === 503 && code === 'HOSTING_FULL') return { kind: 'full' }
    if (response.status === 422) return { kind: 'invalid' }
    return { kind: 'error' }
  })
}

export function endQuiz(quiz: HostedQuiz, fetchFn = send, base = '/api'): Promise<EndResult> {
  return call(async (signal) => {
    const response = await fetchFn(`${base}/quizzes/${encodeURIComponent(quiz.quizId)}/end`, {
      method: 'POST',
      headers: { 'X-Host-Token': quiz.hostToken },
      signal,
    })
    if (response.ok) return { kind: 'ended' }
    const code = await errorCode(response)
    if (response.status === 403) return { kind: 'forbidden' }
    if (code === 'QUIZ_ENDED' || code === 'QUIZ_NOT_FOUND') return { kind: 'gone' }
    return { kind: 'error' }
  })
}

/**
 * The quiz this tab hosts; the host token never leaves the tab's sessionStorage. Storage is resolved
 * inside each `try`, because with storage blocked even reading `sessionStorage` throws.
 */
export function readHostedQuiz(storage?: Storage): HostedQuiz | null {
  try {
    return toHostedQuiz(JSON.parse((storage ?? sessionStorage).getItem(HOST_KEY) ?? 'null'))
  } catch {
    return null
  }
}

export function saveHostedQuiz(quiz: HostedQuiz, storage?: Storage): void {
  try {
    ;(storage ?? sessionStorage).setItem(HOST_KEY, JSON.stringify(quiz))
  } catch {
    // Blocked storage: the controls work until a refresh.
  }
}

export function clearHostedQuiz(storage?: Storage): void {
  try {
    ;(storage ?? sessionStorage).removeItem(HOST_KEY)
  } catch {
    // Nothing was stored.
  }
}
