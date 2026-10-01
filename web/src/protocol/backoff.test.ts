// AI-ASSISTED: tests for the full-jitter backoff, the close-code rules and the limit of failed connects.
import { describe, expect, it } from 'vitest'
import { Backoff, backoffDelay, MAX_FAILED_CONNECTS } from './backoff'

const almostOne = () => 0.999999

describe('backoffDelay', () => {
  it.each([
    [0, 249],
    [1, 499],
    [3, 1999],
    [5, 7999],
    [6, 9999],
    [20, 9999],
  ])('caps attempt %i at %i ms', (attempt, max) => {
    expect(backoffDelay(attempt, almostOne)).toBe(max)
  })

  it('floors random() times the window', () => {
    expect(backoffDelay(2, () => 0)).toBe(0)
    expect(backoffDelay(2, () => 0.5)).toBe(500)
  })
})

describe('Backoff', () => {
  it('grows the window with each failed attempt', () => {
    const backoff = new Backoff(almostOne)
    expect([1006, 1006, 1006].map((code) => backoff.closed(code, 0))).toEqual([249, 499, 999])
  })

  it.each([1006, 1009, 1011, 1012])('reconnects with backoff after %i', (code) => {
    expect(new Backoff(() => 0.5).closed(code, 0)).toBe(125)
  })

  it('waits 5 s plus the backoff after 1013', () => {
    expect(new Backoff(() => 0.5).closed(1013, 0)).toBe(5_125)
  })

  it.each([1000, 1008, 4001])('never reconnects after %i', (code) => {
    expect(new Backoff(almostOne).closed(code, 0)).toBeNull()
  })

  it('resets the counter after 10 s joined', () => {
    const backoff = new Backoff(almostOne)
    backoff.closed(1006, 0)
    backoff.closed(1006, 0)
    backoff.joined(1_000)
    expect(backoff.closed(1006, 11_000)).toBe(249)
  })

  it('keeps the counter when the join lasted less than 10 s', () => {
    const backoff = new Backoff(almostOne)
    backoff.closed(1006, 0)
    backoff.joined(1_000)
    expect(backoff.closed(1006, 10_999)).toBe(499)
  })

  it('gives up after 10 connects in a row without a joined, whatever the codes', () => {
    const backoff = new Backoff(almostOne)
    const codes = [1006, 1009, 1011, 1012, 1013, 1006, 1006, 1006, 1006]
    expect(codes.map((code) => backoff.closed(code, 0))).not.toContain(null)
    expect(backoff.exhausted).toBe(false)
    expect(backoff.closed(1006, 0)).toBeNull()
    expect(backoff.exhausted).toBe(true)
  })

  it('counts failed connects again from zero after any joined, even one shorter than 10 s', () => {
    const backoff = new Backoff(almostOne)
    for (let i = 1; i < MAX_FAILED_CONNECTS; i++) backoff.closed(1006, 0)
    backoff.joined(1_000)
    // The close of the joined link, then 9 failed connects.
    for (let i = 0; i < MAX_FAILED_CONNECTS; i++) expect(backoff.closed(1006, 2_000)).not.toBeNull()
    expect(backoff.closed(1006, 2_000)).toBeNull()
  })

  it('a final close code does not count as exhausted', () => {
    const backoff = new Backoff(almostOne)
    expect(backoff.closed(1008, 0)).toBeNull()
    expect(backoff.exhausted).toBe(false)
  })
})
