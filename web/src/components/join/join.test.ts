// AI-ASSISTED: tests for the join form rules and the remembered name.
import { describe, expect, it } from 'vitest'
import { strings } from '@/strings'
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
