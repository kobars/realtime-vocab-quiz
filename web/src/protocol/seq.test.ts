// AI-ASSISTED: tests for the seq rules of the protocol client.
import { describe, expect, it } from 'vitest'
import { PONG_CHECK_MS, SeqTracker } from './seq'
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
  tracker.joined()
  tracker.snapshot(atSeq)
  return tracker
}

describe('SeqTracker', () => {
  it('sends one resync with the last applied seq on each joined, and keeps L until the snapshot', () => {
    const tracker = trackerAt(4)
    expect(tracker.joined()).toEqual({ apply: [], resync: { lastSeq: 4, delayMs: 0 }, check: null })
    expect(tracker.lastSeq).toBe(4)
    // The link dropped before the snapshot: the next joined resyncs from the same L.
    expect(tracker.joined().resync).toEqual({ lastSeq: 4, delayMs: 0 })
    tracker.snapshot(9)
    expect(tracker.lastSeq).toBe(9)
  })

  it('asks for no second resync after a reconnect until the snapshot', () => {
    const tracker = trackerAt(4)
    tracker.joined()
    expect(tracker.broadcast(board(12)).resync).toBeNull()
    expect(tracker.pong(12).resync).toBeNull()
  })

  it('resets to snapshot.atSeq, drops older buffered frames and applies newer ones in order', () => {
    const tracker = new SeqTracker()
    tracker.joined()
    for (const seq of [8, 6, 7, 5]) tracker.broadcast(board(seq))
    const step = tracker.snapshot(6)
    expect(seqs(step.apply)).toEqual([7, 8])
    expect(step.resync).toBeNull()
    expect(tracker.lastSeq).toBe(8)
  })

  it('applies seq = last + 1 and ignores a duplicate', () => {
    const tracker = trackerAt(3)
    expect(seqs(tracker.broadcast(board(4)).apply)).toEqual([4])
    expect(tracker.broadcast(board(4))).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(4)
  })

  it('waits 0–250 ms on a gap, then asks for one resync and buffers until the snapshot', () => {
    const tracker = trackerAt(3, () => 0.999999)
    expect(tracker.broadcast(board(6))).toEqual({ apply: [], resync: { lastSeq: 3, delayMs: 250 }, check: null })
    expect(tracker.broadcast(board(7))).toEqual({ apply: [], resync: null, check: null })
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
    expect(tracker.broadcast(board(9, true))).toEqual({ apply: [board(9, true)], resync: null, check: null })
    expect(tracker.lastSeq).toBe(9)
  })

  it('resyncs at once on a lower seq (the store restarted) and accepts the lower snapshot', () => {
    const tracker = trackerAt(10)
    expect(tracker.broadcast(board(2)).resync).toEqual({ lastSeq: 10, delayMs: 0 })
    expect(seqs(tracker.snapshot(1).apply)).toEqual([2])
    expect(tracker.lastSeq).toBe(2)
  })

  it.each([6, 5, 3, null])('ignores pong.seq %j at or below L = 6', (seq) => {
    const tracker = trackerAt(6)
    expect(tracker.pong(seq)).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(6)
  })

  it('ignores a pong whose counter read is older than a frame already applied', () => {
    const tracker = trackerAt(10)
    tracker.broadcast(board(11))
    expect(tracker.pong(10).resync).toBeNull()
  })

  it('does not resync at once on a pong.seq above L, but checks again after 1 s', () => {
    expect(PONG_CHECK_MS).toBe(1000)
    expect(trackerAt(6).pong(8)).toEqual({ apply: [], resync: null, check: { pongSeq: 8, delayMs: 1000 } })
  })

  it('resyncs on the pong check when L is still below that pong.seq', () => {
    const tracker = trackerAt(6)
    tracker.pong(8)
    tracker.broadcast(board(7))
    expect(tracker.pongCheck(8).resync).toEqual({ lastSeq: 7, delayMs: 0 })
  })

  it('does nothing on the pong check when the broadcast arrived in time', () => {
    const tracker = trackerAt(6)
    tracker.pong(7)
    tracker.broadcast(board(7))
    expect(tracker.pongCheck(7)).toEqual({ apply: [], resync: null, check: null })
  })

  it('asks for one resync per gap, also when pongs and pong checks follow', () => {
    const tracker = trackerAt(6)
    tracker.pongCheck(8)
    expect(tracker.pong(8).check).toBeNull()
    expect(tracker.pongCheck(8).resync).toBeNull()
    expect(tracker.broadcast(board(9)).resync).toBeNull()
  })

  it('always applies quiz_ended and sets lastSeq, even while resyncing', () => {
    const tracker = trackerAt(3)
    tracker.broadcast(board(6))
    expect(tracker.broadcast(ended(12))).toEqual({ apply: [ended(12)], resync: null, check: null })
    expect(tracker.lastSeq).toBe(12)
    // The snapshot that answers the resync was read before the end: it must not replay frame 6.
    expect(tracker.snapshot(5)).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(12)
  })

  it.each([undefined, 'open'] as const)(
    'keeps lastSeq at the final seq when an older snapshot (status %j) arrives after quiz_ended',
    (status) => {
      const tracker = trackerAt(4)
      tracker.pongCheck(6)
      tracker.broadcast(ended(6))
      expect(tracker.snapshot(4, status)).toEqual({ apply: [], resync: null, check: null })
      expect(tracker.lastSeq).toBe(6)
      expect(tracker.pong(6).resync).toBeNull()
    },
  )

  it('ignores a status open snapshot after quiz_ended, even above the final seq', () => {
    const tracker = trackerAt(4)
    tracker.broadcast(ended(5))
    tracker.joined()
    expect(tracker.snapshot(7, 'open')).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(5)
  })

  it('accepts a snapshot with status ended after quiz_ended', () => {
    const tracker = trackerAt(4)
    tracker.broadcast(ended(5))
    tracker.joined()
    expect(tracker.snapshot(5, 'ended')).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(5)
  })

  it('drops leaderboard frames after quiz_ended instead of resyncing', () => {
    const tracker = trackerAt(3)
    tracker.broadcast(ended(4))
    expect(tracker.broadcast(board(2))).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.broadcast(board(5))).toEqual({ apply: [], resync: null, check: null })
    expect(tracker.lastSeq).toBe(4)
  })
})
