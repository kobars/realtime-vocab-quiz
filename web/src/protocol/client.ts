// AI-ASSISTED: QuizClient owns the socket: connect with a fresh ticket, reconnect through Backoff, SeqTracker wiring, liveness, answer retries, rejoin and leaderboard pages (protocol spec §2.1, §3, §7, §9).
import { Backoff, backoffDelay, OPEN_TIMEOUT_MS } from './backoff'
import { type AuthApi, connectTicket } from './identity'
import { SeqTracker, type SeqStep } from './seq'
import type { Answer, ClientMessage, ErrorCode, ServerMessage } from './types.generated'

export const SUBPROTOCOL = 'quiz.v1'
export const PING_INTERVAL_MS = 25_000
export const LIVENESS_TIMEOUT_MS = 50_000
export const RETRY_AFTER_MS = 1_000
/** A failed or slow open, a failed ticket request and a silent link all count as this close code. */
const DEAD_LINK = 1006
/** Answer errors that mean "not done, send it again"; every other answer error settles the answer. */
const RETRY_ANSWER_ON: readonly ErrorCode[] = ['RATE_LIMITED', 'UNAVAILABLE']

/** The part of the browser WebSocket that the client uses. */
export interface QuizSocket {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  send(data: string): void
  close(code?: number): void
}

/** Server messages in the order to apply them (broadcasts only once SeqTracker releases them), plus status changes. */
export type ClientEvent =
  | ServerMessage
  | { type: 'status'; status: 'connecting' | 'open' | 'resyncing' | 'reconnecting' | 'closed'; code: number | null }

export interface QuizClientOptions {
  api: AuthApi
  onEvent: (event: ClientEvent) => void
  /** Default: `ws(s)://<this host>/ws`. */
  url?: string
  socketFactory?: (url: string, protocol: string) => QuizSocket
  storage?: Storage
  random?: () => number
  now?: () => number
}

type Timer = ReturnType<typeof setTimeout>

/** One quiz session: the UI calls start, next and stop, and never touches the socket. */
export class QuizClient {
  private readonly o: Required<QuizClientOptions>
  private readonly backoff: Backoff
  private readonly tracker: SeqTracker
  private socket: QuizSocket | null = null
  /** True once the current socket opened: before that, `send` would throw, so messages are dropped. */
  private open = false
  private stopped = true
  /** Bumped by start and stop, so a connect that awaited its ticket across them does nothing. */
  private generation = 0
  private quizId = ''
  private displayName = ''
  /** The `lastSeq` of the last resync sent, repeated when the server rate-limits it or is unavailable. */
  private lastResync = 0
  /** `UNAVAILABLE` replies to resyncs since the last snapshot: the backoff attempt of the next retry. */
  private resyncFailures = 0
  /** Answers the server has not settled yet, by `submissionId`, oldest first; kept across reconnects. */
  private readonly unsettled = new Map<string, Answer>()
  /** The `submissionId`s sent on the current socket and not answered yet, oldest first. */
  private inFlight: string[] = []
  /** True once the current socket got `joined`: answers go out at once instead of waiting. */
  private joined = false
  /** Timers of the current connection; a disconnect cancels them all. */
  private readonly timers = new Set<Timer>()
  private liveness: Timer | undefined
  private ping: ReturnType<typeof setInterval> | undefined

  constructor(options: QuizClientOptions) {
    this.o = {
      ...options,
      url: options.url ?? defaultUrl(),
      socketFactory: options.socketFactory ?? ((url, protocol) => new WebSocket(url, protocol)),
      storage: options.storage ?? sessionStorage,
      random: options.random ?? Math.random,
      now: options.now ?? (() => performance.now()),
    }
    this.backoff = new Backoff(this.o.random)
    this.tracker = new SeqTracker(this.o.random)
  }

  start(quizId: string, displayName: string): void {
    this.socket?.close(1000)
    this.disconnect()
    this.generation += 1
    this.quizId = quizId
    this.displayName = displayName
    this.stopped = false
    this.unsettled.clear()
    void this.connect()
  }

  next(questionIndex: number): void {
    this.send({ v: 1, type: 'next', questionIndex })
  }

  /**
   * Answers question `questionIndex` with one new `submissionId`, which it returns. The client sends that same
   * answer until the server settles it: again after each reconnect, and 1 s after `RATE_LIMITED` or `UNAVAILABLE`.
   */
  answer(questionIndex: number, choiceIndex: number): string {
    const submissionId = crypto.randomUUID()
    this.unsettled.set(submissionId, { v: 1, type: 'answer', questionIndex, choiceIndex, submissionId })
    if (this.joined) this.sendAnswer(submissionId)
    return submissionId
  }

  /** Sends `join` again on the open socket; the `joined` reply carries the stored `cursor` and `score`. */
  rejoin(): void {
    this.send({ v: 1, type: 'join', quizId: this.quizId, displayName: this.displayName })
  }

  /** Asks for `limit` standings rows from rank `offset + 1`; the reply is `leaderboard_page`. */
  getLeaderboard(offset: number, limit: number): void {
    this.send({ v: 1, type: 'get_leaderboard', offset, limit })
  }

  /** The user left: close with 1000 and never reconnect. */
  stop(): void {
    this.stopped = true
    this.generation += 1
    this.socket?.close(1000)
    this.disconnect()
    this.emit({ type: 'status', status: 'closed', code: 1000 })
  }

  private async connect(): Promise<void> {
    const generation = this.generation
    this.emit({ type: 'status', status: 'connecting', code: null })
    let ticket: string
    try {
      ;({ ticket } = await connectTicket(this.o.api, this.displayName, this.o.storage))
    } catch {
      if (generation === this.generation) this.closed(DEAD_LINK)
      return
    }
    if (this.stopped || generation !== this.generation) return
    const socket = this.o.socketFactory(`${this.o.url}?ticket=${encodeURIComponent(ticket)}`, SUBPROTOCOL)
    this.socket = socket
    const openTimer = this.after(OPEN_TIMEOUT_MS, () => this.kill(socket))
    socket.onopen = () => {
      clearTimeout(openTimer)
      this.open = true
      this.emit({ type: 'status', status: 'open', code: null })
      this.ping = setInterval(() => this.send({ v: 1, type: 'ping' }), PING_INTERVAL_MS)
      this.alive(socket)
      this.rejoin()
    }
    socket.onmessage = (event) => {
      this.alive(socket)
      this.receive(JSON.parse(String(event.data)) as ServerMessage)
    }
    socket.onclose = (event) => this.closed(event.code)
  }

  private receive(message: ServerMessage): void {
    switch (message.type) {
      case 'joined':
        // The resync goes out before the UI hears of the join.
        this.backoff.joined(this.o.now())
        this.run(this.tracker.joined())
        if (!this.joined) {
          this.joined = true
          for (const submissionId of this.unsettled.keys()) this.sendAnswer(submissionId)
        }
        break
      case 'answer_result':
        this.unsettled.delete(message.submissionId)
        this.inFlight = this.inFlight.filter((id) => id !== message.submissionId)
        break
      case 'leaderboard':
      case 'quiz_ended':
        return this.run(this.tracker.broadcast(message))
      case 'snapshot': {
        // A snapshot read before the end that arrives after quiz_ended changes nothing, so the UI never sees it.
        const stale = this.tracker.readBeforeEnd(message.atSeq, message.status)
        const step = this.tracker.snapshot(message.atSeq, message.status)
        this.resyncFailures = 0
        if (!stale) this.emit(message)
        return this.run(step)
      }
      case 'pong':
        return this.run(this.tracker.pong(message.seq))
      case 'error':
        if (message.requestType === 'resync') this.resyncFailed(message.code)
        if (message.requestType === 'answer') this.answerFailed(message.code)
        break
    }
    this.emit(message)
  }

  /** Repeats the last resync: 1 s after `RATE_LIMITED`, after a backoff wait after `UNAVAILABLE` (spec §7). */
  private resyncFailed(code: ErrorCode): void {
    let wait: number
    if (code === 'RATE_LIMITED') wait = RETRY_AFTER_MS
    else if (code === 'UNAVAILABLE') wait = backoffDelay(this.resyncFailures++, this.o.random)
    else return
    const lastSeq = this.lastResync
    this.after(wait, () => this.send({ v: 1, type: 'resync', lastSeq }))
  }

  /**
   * Applies the released broadcasts in order, sends the tracker's resync now or after its delay, and runs the
   * pong check it asks for.
   */
  private run({ apply, resync, check }: SeqStep): void {
    for (const frame of apply) this.emit(frame)
    if (check !== null) this.after(check.delayMs, () => this.run(this.tracker.pongCheck(check.pongSeq)))
    if (resync === null) return
    const send = () => {
      this.emit({ type: 'status', status: 'resyncing', code: null })
      this.lastResync = resync.lastSeq
      this.send({ v: 1, type: 'resync', lastSeq: resync.lastSeq })
    }
    if (resync.delayMs === 0) send()
    else this.after(resync.delayMs, send)
  }

  private sendAnswer(submissionId: string): void {
    const answer = this.unsettled.get(submissionId)
    if (answer === undefined) return
    this.inFlight.push(submissionId)
    this.send(answer)
  }

  /** An answer error carries no `submissionId`: the server replies in order, so it belongs to the oldest in flight. */
  private answerFailed(code: ErrorCode): void {
    const submissionId = this.inFlight.shift()
    if (submissionId === undefined) return
    if (RETRY_ANSWER_ON.includes(code)) this.after(RETRY_AFTER_MS, () => this.sendAnswer(submissionId))
    else this.unsettled.delete(submissionId)
  }

  /** Sends on an open socket; otherwise drops the message (a reconnect resends answers, `joined` re-drives `next`). */
  private send(message: ClientMessage): void {
    if (this.open) this.socket?.send(JSON.stringify(message))
  }

  /** Restarts the 50 s liveness timer: no inbound message by then closes the link. */
  private alive(socket: QuizSocket): void {
    if (this.liveness !== undefined) this.timers.delete(this.liveness)
    clearTimeout(this.liveness)
    this.liveness = this.after(LIVENESS_TIMEOUT_MS, () => this.kill(socket))
  }

  /** Gives up on a socket that did not open in time or went silent, and handles it as a dead link. */
  private kill(socket: QuizSocket): void {
    socket.onopen = socket.onmessage = socket.onclose = null
    socket.close()
    this.closed(DEAD_LINK)
  }

  private closed(code: number): void {
    this.disconnect()
    if (this.stopped) return
    const wait = this.backoff.closed(code, this.o.now())
    this.stopped = wait === null
    this.emit({ type: 'status', status: wait === null ? 'closed' : 'reconnecting', code })
    if (wait !== null) this.after(wait, () => void this.connect())
  }

  /**
   * Drops the socket and its timers: the open timeout, a pending gap resync, a resync or answer retry, ping and
   * liveness. Unsettled answers stay, for the next `joined`.
   */
  private disconnect(): void {
    if (this.socket !== null) this.socket.onopen = this.socket.onmessage = this.socket.onclose = null
    this.socket = null
    this.open = false
    this.joined = false
    this.resyncFailures = 0
    this.inFlight = []
    for (const timer of this.timers) clearTimeout(timer)
    this.timers.clear()
    clearInterval(this.ping)
  }

  private after(ms: number, run: () => void): Timer {
    const timer = setTimeout(() => this.timers.delete(timer) && run(), ms)
    this.timers.add(timer)
    return timer
  }

  private emit(event: ClientEvent): void {
    this.o.onEvent(event)
  }
}

/** `ws(s)://<this host>/ws`, read only when no url is given. */
function defaultUrl(): string {
  const scheme = globalThis.location?.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${globalThis.location?.host}/ws`
}
