// AI-ASSISTED: tests for the tab identity in sessionStorage and the ticket before each connect.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type AuthApi, IDENTITY_KEY, IDENTITY_TIMEOUT_MS, connectTicket, httpAuthApi } from './identity'

const fakeApi = (tickets: (string | null)[] = []) => {
  let sessions = 0
  return {
    createSession: vi.fn(async () => ({ userId: `u${++sessions}`, sessionToken: `token-${sessions}` })),
    createTicket: vi.fn(async (token: string) => (tickets.length > 0 ? (tickets.shift() ?? null) : `ticket-for-${token}`)),
  } satisfies AuthApi
}

describe('connectTicket', () => {
  beforeEach(() => sessionStorage.clear())

  it('creates the session once and gets a new ticket before every connect', async () => {
    const api = fakeApi(['t1', 't2'])
    const first = await connectTicket(api, 'Ana')
    const second = await connectTicket(api, 'Ana')
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(api.createSession).toHaveBeenCalledWith('Ana')
    expect([first.ticket, second.ticket]).toEqual(['t1', 't2'])
    expect(second.identity).toEqual({ userId: 'u1', sessionToken: 'token-1' })
  })

  it('keeps the player across a reload of the tab (sessionStorage)', async () => {
    sessionStorage.setItem(IDENTITY_KEY, JSON.stringify({ userId: 'kept', sessionToken: 'tok' }))
    const api = fakeApi()
    const { identity, ticket } = await connectTicket(api, 'Ana')
    expect(identity.userId).toBe('kept')
    expect(ticket).toBe('ticket-for-tok')
    expect(api.createSession).not.toHaveBeenCalled()
  })

  it('stores nothing outside the tab, so another tab is another player', async () => {
    await connectTicket(fakeApi(), 'Ana')
    expect(localStorage.length).toBe(0)
    expect(JSON.parse(sessionStorage.getItem(IDENTITY_KEY) ?? '')).toEqual({ userId: 'u1', sessionToken: 'token-1' })
  })

  it.each(['not json', '{"userId": 7}', 'null', '{"userId": "", "sessionToken": "tok"}'])('replaces a broken stored identity %j', async (stored) => {
    sessionStorage.setItem(IDENTITY_KEY, stored)
    expect((await connectTicket(fakeApi(), 'Ana')).identity.userId).toBe('u1')
  })

  it('replaces a session the server no longer knows', async () => {
    sessionStorage.setItem(IDENTITY_KEY, JSON.stringify({ userId: 'old', sessionToken: 'gone' }))
    const { identity, ticket } = await connectTicket(fakeApi([null]), 'Ana')
    expect(identity.userId).toBe('u1')
    expect(ticket).toBe('ticket-for-token-1')
  })

  it('gives overlapping connects one session, each with its own ticket', async () => {
    const api = fakeApi()
    const [a, b] = await Promise.all([connectTicket(api, 'Ana'), connectTicket(api, 'Ana')])
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect([a.identity, b.identity]).toEqual([{ userId: 'u1', sessionToken: 'token-1' }, { userId: 'u1', sessionToken: 'token-1' }])
    expect(api.createTicket).toHaveBeenCalledTimes(2)
    expect(JSON.parse(sessionStorage.getItem(IDENTITY_KEY) ?? '')).toEqual(a.identity)
  })

  it('replaces a forgotten session once when overlapping connects both get a 401', async () => {
    sessionStorage.setItem(IDENTITY_KEY, JSON.stringify({ userId: 'old', sessionToken: 'gone' }))
    const api = fakeApi([null, null])
    const [a, b] = await Promise.all([connectTicket(api, 'Ana'), connectTicket(api, 'Ana')])
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect([a.identity.userId, b.identity.userId]).toEqual(['u1', 'u1'])
    expect(JSON.parse(sessionStorage.getItem(IDENTITY_KEY) ?? '').userId).toBe('u1')
  })

  it('keeps the stored identity when a ticket fails for another reason than 401', async () => {
    const stored = JSON.stringify({ userId: 'kept', sessionToken: 'tok' })
    sessionStorage.setItem(IDENTITY_KEY, stored)
    const api = fakeApi()
    api.createTicket.mockRejectedValueOnce(new Error('POST /api/tickets failed: 503'))
    await expect(connectTicket(api, 'Ana')).rejects.toThrow('503')
    expect(api.createSession).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(IDENTITY_KEY)).toBe(stored)
  })

  it('fails and forgets the session when a new session gets no ticket either', async () => {
    await expect(connectTicket(fakeApi([null]), 'Ana')).rejects.toThrow('refused a ticket')
    expect(sessionStorage.getItem(IDENTITY_KEY)).toBeNull()
  })
})

describe('httpAuthApi', () => {
  const reply = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  it('posts the display name and the bearer token', async () => {
    const fetchFn = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(reply(201, { userId: 'u1', sessionToken: 's1' }))
      .mockResolvedValueOnce(reply(201, { ticket: 'abc', expiresInMs: 30_000 }))
    const api = httpAuthApi('/api', fetchFn)
    expect(await api.createSession('Ana')).toEqual({ userId: 'u1', sessionToken: 's1' })
    expect(await api.createTicket('s1')).toBe('abc')
    const signal = expect.any(AbortSignal)
    expect(fetchFn.mock.calls).toEqual([
      ['/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"displayName":"Ana"}', signal }],
      ['/api/tickets', { method: 'POST', headers: { Authorization: 'Bearer s1' }, signal }],
    ])
  })

  it('maps 401 on a ticket to null and other failures to errors', async () => {
    const fetchFn = vi.fn<typeof fetch>()
    const api = httpAuthApi('/api', fetchFn)
    fetchFn.mockResolvedValueOnce(reply(401, {}))
    expect(await api.createTicket('s1')).toBeNull()
    fetchFn.mockResolvedValueOnce(reply(503, {}))
    await expect(api.createTicket('s1')).rejects.toThrow('503')
    fetchFn.mockResolvedValueOnce(reply(500, {}))
    await expect(api.createSession('Ana')).rejects.toThrow('500')
  })

  it('rejects a reply without the expected fields', async () => {
    const fetchFn = vi.fn<typeof fetch>()
    const api = httpAuthApi('/api', fetchFn)
    fetchFn.mockResolvedValueOnce(reply(201, { userId: 'u1' }))
    await expect(api.createSession('Ana')).rejects.toThrow('no userId and sessionToken')
    fetchFn.mockResolvedValueOnce(reply(201, { expiresInMs: 30_000 }))
    await expect(api.createTicket('s1')).rejects.toThrow('no ticket')
  })

  it.each([
    ['session', (api: AuthApi) => api.createSession('Ana')],
    ['ticket', (api: AuthApi) => api.createTicket('s1')],
  ])('fails a %s request that never answers after 5 s and aborts it', async (_, request) => {
    vi.useFakeTimers()
    try {
      const fetchFn = vi.fn<typeof fetch>(() => new Promise(() => undefined))
      const outcome = request(httpAuthApi('/api', fetchFn)).catch((error: unknown) => error)
      await vi.advanceTimersByTimeAsync(IDENTITY_TIMEOUT_MS - 1)
      expect(fetchFn.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      expect(await outcome).toMatchObject({ name: 'TimeoutError' })
      expect(fetchFn.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})
