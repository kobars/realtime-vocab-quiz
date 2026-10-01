// AI-ASSISTED: tests for the full-jitter backoff and the close-code rules.
import { describe, expect, it } from 'vitest'
import { Backoff, backoffDelay } from './backoff'

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
})
