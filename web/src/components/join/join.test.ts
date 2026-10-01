// AI-ASSISTED: tests for the join form rules, the remembered name and the quiz preview request.
import { describe, expect, it, vi } from 'vitest'
import { strings } from '@/strings'
import { fetchQuizPreview } from './preview'
import { displayNameError, normalizeQuizId, quizIdError, readName, saveName } from './validation'

describe('quiz ID', () => {
  it('upper-cases what is typed', () => expect(normalizeQuizId('vocab-42')).toBe('VOCAB-42'))

  it.each(['VOCAB-42', 'ABC', 'A-B-C-1234567890'])('accepts %s', (id) => expect(quizIdError(id)).toBeNull())

  it.each(['', 'AB', 'VOCAB_42', 'VOCAB 42', 'vocab-42', 'A-B-C-12345678901'])('rejects "%s"', (id) =>
    expect(quizIdError(id)).toBe(strings.join.quizIdInvalid))
})

describe('display name', () => {
  it.each([['', strings.join.nameRequired], ['   ', strings.join.nameRequired], ['x'.repeat(33), strings.join.nameTooLong]])(
    'rejects "%s"', (name, message) => expect(displayNameError(name)).toBe(message))

  it('counts characters after the trim', () => {
    expect(displayNameError(`  ${'x'.repeat(32)}  `)).toBeNull()
    expect(displayNameError('🦊'.repeat(32))).toBeNull()
  })

  it('is remembered in the tab and survives broken storage', () => {
    saveName('Ana')
    expect(readName()).toBe('Ana')
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } } as unknown as Storage
    expect(() => saveName('Bo', broken)).not.toThrow()
    expect(readName(broken)).toBe('')
  })
})

describe('quiz preview', () => {
  const reply = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }))
  const open = { title: 'Everyday words', questionCount: 10, status: 'open', playerCount: 3 }

  it('reads the public quiz information', async () => {
    const fetchFn = reply(200, open)
    expect(await fetchQuizPreview('VOCAB-42', fetchFn)).toEqual({ kind: 'found', quiz: open })
    expect(fetchFn).toHaveBeenCalledWith('/api/quizzes/VOCAB-42')
  })

  it('maps 404 to not found', async () =>
    expect(await fetchQuizPreview('NOPE-1', reply(404, { title: '' }))).toEqual({ kind: 'not-found' }))

  it.each([
    ['a server error', reply(503, {})],
    ['a body of the wrong shape', reply(200, { ...open, status: 'paused' })],
    ['a network failure', vi.fn(async () => Promise.reject(new TypeError('offline')))],
  ])('treats %s as unavailable', async (_, fetchFn) =>
    expect(await fetchQuizPreview('VOCAB-42', fetchFn)).toEqual({ kind: 'unavailable' }))
})
