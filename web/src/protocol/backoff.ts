// AI-ASSISTED: reconnect policy of the protocol client: full-jitter backoff and the close-code rules (protocol spec §7).

export const OPEN_TIMEOUT_MS = 5_000
export const OVERLOAD_WAIT_MS = 5_000
export const BACKOFF_RESET_MS = 10_000
const BACKOFF_BASE_MS = 250
const BACKOFF_CAP_MS = 10_000

/** Close codes after which the client never reconnects: left or ended, policy violation, replaced by another tab. */
const FINAL_CLOSE_CODES: ReadonlySet<number> = new Set([1000, 1008, 4001])

/** Full jitter: `floor(random() × min(10000, 250 × 2^attempt))` ms. */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  return Math.floor(random() * Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** attempt))
}

/**
 * Tracks the attempt counter across reconnects. Times come from the caller, so the
 * policy runs on fake clocks in tests. The counter resets once a connection has stayed
 * joined for 10 s.
 */
export class Backoff {
  private attempt = 0
  private joinedAt: number | null = null

  constructor(private readonly random: () => number = Math.random) {}

  /** The server confirmed the join at `now` (ms, monotonic). */
  joined(now: number): void {
    this.joinedAt = now
  }

  /**
   * The socket closed with `code` (1006 for a failed open or a dead link) at `now`.
   * Returns the wait before the next connect, or null when the client must not reconnect.
   */
  closed(code: number, now: number): number | null {
    if (this.joinedAt !== null && now - this.joinedAt >= BACKOFF_RESET_MS) this.attempt = 0
    this.joinedAt = null
    if (FINAL_CLOSE_CODES.has(code)) return null
    const wait = backoffDelay(this.attempt, this.random)
    this.attempt += 1
    return code === 1013 ? OVERLOAD_WAIT_MS + wait : wait
  }
}
