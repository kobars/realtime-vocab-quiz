// AI-ASSISTED: tests for the join form rules, the remembered name and the quiz preview request.
import { describe, expect, it, vi } from 'vitest'
import { strings } from '@/strings'
import { fetchQuizPreview } from './preview'
import { displayNameError, normalizeQuizId, quizIdError, readName, saveName } from './validation'

describe('quiz ID', () => {
  it('upper-cases what is typed', () => expect(normalizeQuizId('vocab-42')).toBe('VOCAB-42'))

  it.each(['VOCAB-42', 'VOCAB-42-7K3Q', 'ABC', 'A-B-C-1234567890'])('accepts %s', (id) => expect(quizIdError(id)).toBeNull())

  it.each(['', 'AB', 'VOCAB_42', 'VOCAB 42', 'vocab-42', 'A-B-C-12345678901'])('rejects "%s"', (id) =>
    expect(quizIdError(id)).toBe(strings.join.quizIdInvalid))

  it.each([strings.join.quizIdHint, strings.join.quizIdInvalid])('"%s" names a run ID, which the pattern accepts', (copy) => {
    const example = copy.match(/[A-Z0-9]+(?:-[A-Z0-9]+){2,}/)?.[0] ?? ''
    expect(example).toBe('VOCAB-42-7K3Q')
    expect(quizIdError(example)).toBeNull()
  })
})

describe('display name', () => {
  it.each([['', strings.join.nameRequired], ['   ', strings.join.nameRequired], ['x'.repeat(33), strings.join.nameTooLong]])(
    'rejects "%s"', (name, message) => expect(displayNameError(name)).toBe(message))

  it('counts characters after the trim', () => {
    expect(displayNameError(`  ${'x'.repeat(32)}  `)).toBeNull()
    expect(displayNameError('🦊'.repeat(32))).toBeNull()
  })

  it('counts characters after NFC normalization, like the server', () => {
    const decomposed = 'é'.repeat(20)
    expect([...decomposed].length).toBe(40)
    expect(displayNameError(decomposed)).toBeNull()
  })

  it('is remembered in the tab and survives broken storage', () => {
    saveName('Ana')
    expect(readName()).toBe('Ana')
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } } as unknown as Storage
    expect(() => saveName('Bo', broken)).not.toThrow()
    expect(readName(broken)).toBe('')
  })

  it('survives a sessionStorage property that throws on access', () => {
    const blocked = vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    try {
      expect(readName()).toBe('')
      expect(() => saveName('Bo')).not.toThrow()
    } finally {
      blocked.mockRestore()
    }
  })
})

describe('quiz preview', () => {
  const reply = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }))
  const open = { title: 'Everyday words', questionCount: 10, status: 'open', players: 3 }

  it('reads the public quiz information', async () => {
    const fetchFn = reply(200, open)
    expect(await fetchQuizPreview('VOCAB-42', fetchFn)).toEqual({ kind: 'found', quiz: open })
    expect(fetchFn).toHaveBeenCalledWith('/api/quizzes/VOCAB-42', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('maps the endpoint\'s own 404 to not found', async () =>
    expect(await fetchQuizPreview('NOPE-1', reply(404, { error: 'QUIZ_NOT_FOUND', message: 'Quiz not found.' })))
      .toEqual({ kind: 'not-found' }))

  it.each([
    ['a server error', reply(503, {})],
    ['a body of the wrong shape', reply(200, { ...open, status: 'paused' })],
    ['a network failure', vi.fn(async () => Promise.reject(new TypeError('offline')))],
    ['a 404 from a missing route', reply(404, { detail: 'Not Found' })],
    ['a 404 without a JSON body', vi.fn(async () => new Response('<h1>Not Found</h1>', { status: 404 }))],
  ])('treats %s as unavailable', async (_, fetchFn) =>
    expect(await fetchQuizPreview('VOCAB-42', fetchFn)).toEqual({ kind: 'unavailable' }))

  it('gives up on a request that never answers and aborts it', async () => {
    let signal: AbortSignal | undefined
    const fetchFn = vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal ?? undefined
      return new Promise<Response>(() => {})
    })
    expect(await fetchQuizPreview('VOCAB-42', fetchFn, '/api', 10)).toEqual({ kind: 'unavailable' })
    expect(signal?.aborted).toBe(true)
  })

  it('gives up on a body that never finishes', async () => {
    const fetchFn = vi.fn(async () => new Response(new ReadableStream({ start: () => {} }), { status: 200 }))
    expect(await fetchQuizPreview('VOCAB-42', fetchFn, '/api', 10)).toEqual({ kind: 'unavailable' })
  })
})
