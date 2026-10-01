// AI-ASSISTED: the tab's mock identity in sessionStorage and a fresh one-time ticket before every connect (protocol spec §8).

export interface Identity {
  userId: string
  sessionToken: string
}

/** The two HTTP calls of the mock identity service. */
export interface AuthApi {
  createSession(displayName: string): Promise<Identity>
  /** Resolves to null when the server no longer knows the session (HTTP 401). */
  createTicket(sessionToken: string): Promise<string | null>
}

export const IDENTITY_KEY = 'quiz.identity'

function toIdentity(value: unknown): Identity | null {
  if (typeof value !== 'object' || value === null) return null
  const { userId, sessionToken } = value as Record<string, unknown>
  const valid = typeof userId === 'string' && userId !== '' && typeof sessionToken === 'string' && sessionToken !== ''
  return valid ? { userId, sessionToken } : null
}

function readIdentity(storage: Storage): Identity | null {
  try {
    return toIdentity(JSON.parse(storage.getItem(IDENTITY_KEY) ?? 'null'))
  } catch {
    return null
  }
}

/**
 * Returns a ticket for the next connect. The identity lives in `sessionStorage`, so a reload
 * keeps the player and a second tab is a second player. An unknown session is replaced once.
 */
export async function connectTicket(
  api: AuthApi,
  displayName: string,
  storage: Storage = sessionStorage,
): Promise<{ identity: Identity; ticket: string }> {
  const stored = readIdentity(storage)
  if (stored !== null) {
    const ticket = await api.createTicket(stored.sessionToken)
    if (ticket !== null) return { identity: stored, ticket }
  }
  const identity = await api.createSession(displayName)
  storage.setItem(IDENTITY_KEY, JSON.stringify(identity))
  const ticket = await api.createTicket(identity.sessionToken)
  if (ticket === null) {
    storage.removeItem(IDENTITY_KEY)
    throw new Error('the server refused a ticket for a new session')
  }
  return { identity, ticket }
}

/** `POST {base}/sessions {displayName}` → `{userId, sessionToken}`; `POST {base}/tickets` with the bearer token → `{ticket}`. */
export function httpAuthApi(base = '/api', fetchFn: typeof fetch = (...args) => fetch(...args)): AuthApi {
  return {
    async createSession(displayName) {
      const response = await fetchFn(`${base}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ displayName }),
      })
      if (!response.ok) throw new Error(`POST ${base}/sessions failed: ${response.status}`)
      const identity = toIdentity(await response.json())
      if (identity === null) throw new Error(`POST ${base}/sessions returned no userId and sessionToken`)
      return identity
    },
    async createTicket(sessionToken) {
      const response = await fetchFn(`${base}/tickets`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${sessionToken}` },
      })
      if (response.status === 401) return null
      if (!response.ok) throw new Error(`POST ${base}/tickets failed: ${response.status}`)
      const { ticket } = (await response.json()) as { ticket?: unknown }
      if (typeof ticket !== 'string' || ticket === '') throw new Error(`POST ${base}/tickets returned no ticket`)
      return ticket
    },
  }
}
