// AI-ASSISTED: SeqTracker applies broadcasts in seq order and decides when to resync (protocol spec §3).
import type { Leaderboard, QuizEnded } from './types.generated'

export type Broadcast = Leaderboard | QuizEnded

export const GAP_WAIT_MAX_MS = 250

/** What the caller does after one inbound message. */
export interface SeqStep {
  /** Broadcasts to apply now, in this order. */
  apply: Broadcast[]
  /** Send one `resync {lastSeq}` after `delayMs`, or nothing. */
  resync: { lastSeq: number; delayMs: number } | null
}

const nothing = (): SeqStep => ({ apply: [], resync: null })

/**
 * Tracks the last applied broadcast `seq` (L). It never sends or waits itself: each method
 * returns the frames to apply and at most one resync to send. From a resync until the
 * snapshot it buffers broadcasts instead of applying them, so it asks for one resync at a time.
 */
export class SeqTracker {
  private last = 0
  private resyncing = false
  private buffer: Broadcast[] = []

  constructor(private readonly random: () => number = Math.random) {}

  get lastSeq(): number {
    return this.last
  }

  /** `joined` on a new connection: send exactly one resync with the last seq applied, then reset to `atSeq`. */
  joined(atSeq: number): SeqStep {
    const lastSeq = this.last
    this.last = atSeq
    this.buffer = []
    this.resyncing = true
    return { apply: [], resync: { lastSeq, delayMs: 0 } }
  }

  broadcast(frame: Broadcast): SeqStep {
    // quiz_ended is the last broadcast of a quiz: always applied, whatever its seq.
    if (frame.type === 'quiz_ended') {
      this.last = frame.seq
      return { apply: [frame], resync: null }
    }
    if (this.resyncing) {
      this.buffer.push(frame)
      return nothing()
    }
    const last = this.last
    if (frame.seq === last + 1 || (frame.seq > last + 1 && frame.rebase)) {
      this.last = frame.seq
      return { apply: [frame], resync: null }
    }
    if (frame.seq === last) return nothing()
    this.buffer.push(frame)
    // A gap waits 0–250 ms; a lower seq means the store restarted, so resync at once.
    const delayMs = frame.seq > last ? Math.floor(this.random() * (GAP_WAIT_MAX_MS + 1)) : 0
    return this.startResync(delayMs)
  }

  /** `pong.seq` above L means a lost last frame; below L, a restarted store. */
  pong(seq: number | null): SeqStep {
    if (seq === null || this.resyncing || seq === this.last) return nothing()
    return this.startResync(0)
  }

  /** The snapshot replaces the standings: L = its `atSeq`, then the buffered newer broadcasts apply in order. */
  snapshot(atSeq: number): SeqStep {
    this.last = atSeq
    this.resyncing = false
    const buffered = this.buffer.filter((frame) => frame.seq > atSeq).sort((a, b) => a.seq - b.seq)
    this.buffer = []
    const step = nothing()
    for (const frame of buffered) {
      const next = this.broadcast(frame)
      step.apply.push(...next.apply)
      step.resync ??= next.resync
    }
    return step
  }

  private startResync(delayMs: number): SeqStep {
    this.resyncing = true
    return { apply: [], resync: { lastSeq: this.last, delayMs } }
  }
}
