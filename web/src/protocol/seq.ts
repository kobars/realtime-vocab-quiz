// AI-ASSISTED: SeqTracker applies broadcasts in seq order and decides when to resync (protocol spec §3).
import type { Leaderboard, QuizEnded, Snapshot } from './types.generated'

export type Broadcast = Leaderboard | QuizEnded

export const GAP_WAIT_MAX_MS = 250
/** How long a `pong.seq` above L may wait for its broadcast before the client resyncs. */
export const PONG_CHECK_MS = 1000
/** The most broadcasts held until a snapshot: the newest, as the snapshot drops older ones (a resync can wait long). */
export const BUFFER_MAX = 64

/** What the caller does after one inbound message. */
export interface SeqStep {
  /** Broadcasts to apply now, in this order. */
  apply: Broadcast[]
  /** Send one `resync {lastSeq}` after `delayMs`, or nothing. */
  resync: { lastSeq: number; delayMs: number } | null
  /** Call `pongCheck(pongSeq)` after `delayMs`, or nothing. */
  check: { pongSeq: number; delayMs: number } | null
}

const nothing = (): SeqStep => ({ apply: [], resync: null, check: null })

/**
 * Tracks the last applied broadcast `seq` (L). It never sends or waits itself: each method
 * returns the frames to apply, at most one resync to send and at most one later check. From a resync until the
 * snapshot it buffers broadcasts instead of applying them, so it asks for one resync at a time.
 */
export class SeqTracker {
  private last = 0
  private resyncing = false
  private buffer: Broadcast[] = []
  /** The seq of the applied `quiz_ended`: from then on the standings are final. */
  private finalSeq: number | null = null

  constructor(private readonly random: () => number = Math.random) {}

  get lastSeq(): number {
    return this.last
  }

  /**
   * `joined` on a new connection: send exactly one resync with the last seq applied. L stays: `joined.atSeq`
   * never moves it, only the snapshot does.
   */
  joined(): SeqStep {
    this.buffer = []
    return this.startResync(0)
  }

  broadcast(frame: Broadcast): SeqStep {
    // quiz_ended is the last broadcast of a quiz: always applied, whatever its seq.
    if (frame.type === 'quiz_ended') {
      this.last = frame.seq
      this.finalSeq = frame.seq
      return { ...nothing(), apply: [frame] }
    }
    // No script publishes after the end, so a leaderboard frame that arrives now is older.
    if (this.finalSeq !== null) return nothing()
    if (this.resyncing) {
      this.hold(frame)
      return nothing()
    }
    const last = this.last
    if (frame.seq === last + 1 || (frame.seq > last + 1 && frame.rebase)) {
      this.last = frame.seq
      return { ...nothing(), apply: [frame] }
    }
    if (frame.seq === last) return nothing()
    this.hold(frame)
    // A gap waits 0–250 ms; a lower seq means the store restarted, so resync at once.
    const delayMs = frame.seq > last ? Math.floor(this.random() * (GAP_WAIT_MAX_MS + 1)) : 0
    return this.startResync(delayMs)
  }

  /**
   * `pong.seq` above L: a broadcast is on its way or was lost, so check again after
   * PONG_CHECK_MS. At or below L (a counter read older than a relayed frame) or null: ignore.
   */
  pong(seq: number | null): SeqStep {
    if (seq === null || this.resyncing || seq <= this.last) return nothing()
    return { ...nothing(), check: { pongSeq: seq, delayMs: PONG_CHECK_MS } }
  }

  /** The check a `pong` asked for: resync if L is still below that `pong.seq`. */
  pongCheck(pongSeq: number): SeqStep {
    if (this.resyncing || pongSeq <= this.last) return nothing()
    return this.startResync(0)
  }

  /**
   * The snapshot replaces the standings: L = its `atSeq`, then the buffered newer broadcasts apply in order.
   * After `quiz_ended`, a snapshot read before the end (`status: open`, or without a status an `atSeq`
   * below the final seq) only ends the resync: the final standings and L stay.
   */
  snapshot(atSeq: number, status?: Snapshot['status']): SeqStep {
    this.resyncing = false
    if (this.readBeforeEnd(atSeq, status)) {
      this.buffer = []
      return nothing()
    }
    this.last = atSeq
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

  /** True when `quiz_ended` was applied and this snapshot was read before it, so `snapshot` ignores it. */
  readBeforeEnd(atSeq: number, status?: Snapshot['status']): boolean {
    if (this.finalSeq === null) return false
    return status === 'open' || (status === undefined && atSeq < this.finalSeq)
  }

  private hold(frame: Broadcast): void {
    this.buffer.push(frame)
    if (this.buffer.length > BUFFER_MAX) this.buffer.shift()
  }

  private startResync(delayMs: number): SeqStep {
    this.resyncing = true
    return { ...nothing(), resync: { lastSeq: this.last, delayMs } }
  }
}
