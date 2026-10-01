// AI-ASSISTED: tests for the seq rules of the protocol client.
import { describe, expect, it } from 'vitest'
import { SeqTracker } from './seq'
import type { Leaderboard, QuizEnded } from './types.generated'

const board = (seq: number, rebase = false): Leaderboard => ({
  v: 1,
  type: 'leaderboard',
  seq,
  rebase,
  playerCount: 1,
  onlineCount: 1,
  entries: [],
})
const ended = (seq: number): QuizEnded => ({
  v: 1,
  type: 'quiz_ended',
  seq,
  playerCount: 1,
  entries: [],
  you: null,
})
const seqs = (frames: { seq: number }[]) => frames.map((frame) => frame.seq)

/** A tracker that has applied a snapshot at `atSeq`. */
const trackerAt = (atSeq: number, random = () => 0.5) => {
  const tracker = new SeqTracker(random)
  tracker.joined(0)
  tracker.snapshot(atSeq)
  return tracker
}

describe('SeqTracker', () => {
  it('sends one resync with the last applied seq on joined, then resets to atSeq', () => {
    const tracker = trackerAt(4)
    expect(tracker.joined(9)).toEqual({ apply: [], resync: { lastSeq: 4, delayMs: 0 } })
    expect(tracker.lastSeq).toBe(9)
  })

  it('asks for no second resync after a reconnect until the snapshot', () => {
    const tracker = trackerAt(4)
    tracker.joined(9)
    expect(tracker.broadcast(board(12)).resync).toBeNull()
    expect(tracker.pong(12).resync).toBeNull()
  })

  it('resets to snapshot.atSeq, drops older buffered frames and applies newer ones in order', () => {
    const tracker = new SeqTracker()
    tracker.joined(0)
    for (const seq of [8, 6, 7, 5]) tracker.broadcast(board(seq))
    const step = tracker.snapshot(6)
    expect(seqs(step.apply)).toEqual([7, 8])
    expect(step.resync).toBeNull()
    expect(tracker.lastSeq).toBe(8)
  })

  it('applies seq = last + 1 and ignores a duplicate', () => {
    const tracker = trackerAt(3)
    expect(seqs(tracker.broadcast(board(4)).apply)).toEqual([4])
    expect(tracker.broadcast(board(4))).toEqual({ apply: [], resync: null })
    expect(tracker.lastSeq).toBe(4)
  })

  it('waits 0–250 ms on a gap, then asks for one resync and buffers until the snapshot', () => {
    const tracker = trackerAt(3, () => 0.999999)
    expect(tracker.broadcast(board(6))).toEqual({ apply: [], resync: { lastSeq: 3, delayMs: 250 } })
    expect(tracker.broadcast(board(7))).toEqual({ apply: [], resync: null })
    expect(seqs(tracker.snapshot(5).apply)).toEqual([6, 7])
  })

  it('draws the gap wait from random()', () => {
    expect(trackerAt(3, () => 0).broadcast(board(5)).resync?.delayMs).toBe(0)
  })

  it('asks again when the buffered frames still have a gap after the snapshot', () => {
    const tracker = trackerAt(3)
    tracker.broadcast(board(9))
    expect(tracker.snapshot(5).resync).toEqual({ lastSeq: 5, delayMs: 125 })
  })

  it('accepts a rebase frame after a gap with no resync', () => {
    const tracker = trackerAt(3)
    expect(tracker.broadcast(board(9, true))).toEqual({ apply: [board(9, true)], resync: null })
    expect(tracker.lastSeq).toBe(9)
  })

  it('resyncs at once on a lower seq (the store restarted) and accepts the lower snapshot', () => {
    const tracker = trackerAt(10)
    expect(tracker.broadcast(board(2)).resync).toEqual({ lastSeq: 10, delayMs: 0 })
    expect(seqs(tracker.snapshot(1).apply)).toEqual([2])
    expect(tracker.lastSeq).toBe(2)
  })

  it.each([
    [7, { lastSeq: 6, delayMs: 0 }],
    [3, { lastSeq: 6, delayMs: 0 }],
    [6, null],
    [null, null],
  ])('on pong.seq %j asks for %j', (seq, resync) => {
    expect(trackerAt(6).pong(seq)).toEqual({ apply: [], resync })
  })

  it('asks for one resync per gap, also when pongs follow', () => {
    const tracker = trackerAt(6)
    tracker.pong(8)
    expect(tracker.pong(8).resync).toBeNull()
    expect(tracker.broadcast(board(9)).resync).toBeNull()
  })

  it('always applies quiz_ended and sets lastSeq, even while resyncing', () => {
    const tracker = trackerAt(3)
    tracker.broadcast(board(6))
    expect(tracker.broadcast(ended(12))).toEqual({ apply: [ended(12)], resync: null })
    expect(tracker.lastSeq).toBe(12)
  })
})
