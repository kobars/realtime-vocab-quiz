// AI-ASSISTED: QuizClient owns the socket: connect with a fresh ticket, reconnect through Backoff, SeqTracker wiring, liveness, answer and next retries, rejoin and leaderboard pages (protocol spec §2.1, §3, §7, §9).
import { Backoff, backoffDelay, OPEN_TIMEOUT_MS } from './backoff'
import { type AuthApi, connectTicket } from './identity'
import { SeqTracker, type SeqStep } from './seq'
import type { Answer, ClientMessage, ErrorCode, ServerMessage } from './types.generated'

export const SUBPROTOCOL = 'quiz.v1'
export const PING_INTERVAL_MS = 25_000
export const LIVENESS_TIMEOUT_MS = 50_000
export const RETRY_AFTER_MS = 1_000
/** A resync, `join`, `next` or answer whose reply has not arrived by then is sent again: the token bucket may have dropped it silently. */
export const REPLY_TIMEOUT_MS = 5_000
/** A failed or slow open, a failed ticket request and a silent link all count as this close code. */
const DEAD_LINK = 1006
/** Errors that mean "not done": the answer or `next` stays unsettled and goes out again. Every other error settles it. */
export const RETRY_ON: readonly ErrorCode[] = ['RATE_LIMITED', 'UNAVAILABLE', 'NOT_JOINED']

/** The part of the browser WebSocket that the client uses. */
export interface QuizSocket {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  send(data: string): void
  close(code?: number): void
}

/**
 * Server messages in the order to apply them (broadcasts only once SeqTracker releases them), plus status changes.
 * `closed` follows a final close code or `stop`; `failed` means the client gave up after 10 connects without a `joined`.
 * `identity` names the user each connect signs in as, before its socket opens: a join to an ended quiz gets no `joined`.
 */
export type ClientEvent =
  | Exclude<ServerMessage, { type: 'pong' | 'question' }>
  | QuestionEvent
  | { type: 'identity'; userId: string }
  | { type: 'status'; status: 'connecting' | 'open' | 'resyncing' | 'reconnecting' | 'closed' | 'failed'; code: number | null }

/**
 * A `question`, plus `askedMsAgo`: how long ago this client last sent the `next` for its index on this socket, when it
 * did. The server computed `remainingMs` after that send, so the countdown starts that long before the arrival (protocol §6).
 */
export type QuestionEvent = Extract<ServerMessage, { type: 'question' }> & { askedMsAgo?: number }

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
  /** The `lastSeq` of the resync sent on the current socket with no `snapshot` yet, or null. */
  private outstandingResync: number | null = null
  /** The one timer of the outstanding resync: its retry after an error, or else its snapshot deadline. */
  private resyncRetry: Timer | undefined
  /** `UNAVAILABLE` replies to resyncs since the last snapshot: the backoff attempt of the next retry. */
  private resyncFailures = 0
  /** `UNAVAILABLE` replies to joins since the last `joined`: the backoff attempt of the next retry. */
  private joinFailures = 0
  /** Answers the server has not settled yet, by `submissionId`, oldest first; kept across reconnects. */
  private readonly unsettled = new Map<string, Answer>()
  /** The `submissionId`s sent on the current socket and not answered yet, oldest first. */
  private inFlight: string[] = []
  /**
   * The `next` sent on the current socket with no `question`, `finished` or final error yet, the `UNAVAILABLE`
   * replies it got (the backoff attempt of its next retry), and whether it got `NOT_JOINED` and waits for `joined`.
   */
  private pendingNext: { questionIndex: number; failures: number; afterJoin: boolean } | null = null
  /**
   * The last `next` sent on the current socket, and when. It stays after its `question`, so a second reply (to a resend
   * after a slow first reply) is also timed from the latest send, never from the first one.
   */
  private lastNextSent: { questionIndex: number; at: number } | null = null
  /** The scheduled resend of `pendingNext`: its retry after an error, or else its reply deadline. */
  private nextRetry: Timer | undefined
  /** True once the current socket got `joined`, and false again after `NOT_JOINED`: answers go out only while true. */
  private joined = false
  /** True from a `join` sent on the current socket until its `joined` or a final error, through all its resends. */
  private joining = false
  /** True while the `join` in flight was sent and waits for its reply; false while it waits on its backoff after `UNAVAILABLE`. */
  private joinSent = false
  /** The one timer of the `join` in flight: its retry after an error, or else its reply deadline. */
  private joinRetry: Timer | undefined
  /** The one timer of each unsettled answer, by `submissionId`: its retry after an error, or else its reply deadline. */
  private readonly answerRetries = new Map<string, Timer>()
  /** `UNAVAILABLE` retries so far, by `submissionId`: the backoff attempt of the next one. */
  private readonly unavailable = new Map<string, number>()
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
    this.dropRequests()
    void this.connect()
  }

  /**
   * Asks for question `questionIndex` (or the result, at N). The client sends the same `next` again 1 s after
   * `RATE_LIMITED`, after the backoff after `UNAVAILABLE`, after the `joined` that follows `NOT_JOINED` and
   * REPLY_TIMEOUT_MS after a send with no reply, until a reply arrives. A `next` with no open socket is dropped; a disconnect or `quiz_ended` forgets it.
   */
  next(questionIndex: number): void {
    this.cancelNextRetry()
    if (!this.open) return
    this.pendingNext = { questionIndex, failures: 0, afterJoin: false }
    this.sendNext()
  }

  /**
   * Answers question `questionIndex` with one new `submissionId`, which it returns. The client sends that same
   * answer until the server settles it: again after each `joined`, 1 s after `RATE_LIMITED`, after the backoff
   * after `UNAVAILABLE` and REPLY_TIMEOUT_MS after a send with no reply. `quiz_ended` forgets it.
   */
  answer(questionIndex: number, choiceIndex: number): string {
    const submissionId = crypto.randomUUID()
    this.unsettled.set(submissionId, { v: 1, type: 'answer', questionIndex, choiceIndex, submissionId })
    this.sendAnswer(submissionId)
    return submissionId
  }

  /**
   * Sends `join` again on the open socket; the `joined` reply carries the stored `cursor` and `score`. The same `join`
   * goes out again 1 s after a `RATE_LIMITED` that names no request, after the backoff after `UNAVAILABLE` and
   * REPLY_TIMEOUT_MS after a send with no reply, until `joined` or another join error.
   */
  rejoin(): void {
    this.joining = this.joinSent = this.open
    this.send({ v: 1, type: 'join', quizId: this.quizId, displayName: this.displayName })
    this.retryJoin(REPLY_TIMEOUT_MS)
  }

  /** Asks for a fresh `snapshot` after a random 0–250 ms wait, with the resync's reply deadline and retries. */
  refresh(): void {
    this.run(this.tracker.refresh())
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
    let userId: string
    try {
      ;({ ticket, identity: { userId } } = await connectTicket(this.o.api, this.displayName, this.o.storage))
    } catch {
      if (generation === this.generation) this.closed(DEAD_LINK)
      return
    }
    if (this.stopped || generation !== this.generation) return
    this.emit({ type: 'identity', userId })
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
      case 'joined': {
        // A second `joined` answers a join sent again while the first was only slow: the socket is joined already.
        if (!this.joining) return
        // The resync goes out before the UI hears of the join.
        this.backoff.joined(this.o.now())
        this.run(this.tracker.joined())
        this.joining = this.joinSent = false
        this.cancel(this.joinRetry)
        this.joinFailures = 0
        if (!this.joined) {
          this.joined = true
          for (const submissionId of this.unsettled.keys()) this.sendAnswer(submissionId)
        }
        const waiting = this.pendingNext?.afterJoin === true ? this.pendingNext : null
        this.emit(message)
        // Protocol spec §7: repeat the `next` that got NOT_JOINED, unless the UI asked for another one on `joined`.
        if (waiting !== null && this.pendingNext === waiting) {
          waiting.afterJoin = false
          this.sendNext()
        }
        return
      }
      case 'question':
      case 'finished':
        if (message.type === 'finished' || message.questionIndex === this.pendingNext?.questionIndex) {
          this.cancelNextRetry()
          this.pendingNext = null
        }
        if (message.type === 'question' && message.questionIndex === this.lastNextSent?.questionIndex) {
          return this.emit({ ...message, askedMsAgo: this.o.now() - this.lastNextSent.at })
        }
        break
      case 'answer_result':
        this.settle(message.submissionId)
        this.inFlight = this.inFlight.filter((id) => id !== message.submissionId)
        break
      case 'rank_update':
      case 'leaderboard_page':
        break
      case 'quiz_ended':
        // Ui spec §4.3: the end drops any pending request.
        this.dropRequests()
        return this.run(this.tracker.broadcast(message))
      case 'leaderboard':
        return this.run(this.tracker.broadcast(message))
      case 'snapshot': {
        // A snapshot read before the end that arrives after quiz_ended changes nothing, so the UI never sees it.
        const stale = this.tracker.readBeforeEnd(message.atSeq, message.status)
        const step = this.tracker.snapshot(message.atSeq, message.status)
        this.outstandingResync = null
        this.cancel(this.resyncRetry)
        this.resyncFailures = 0
        if (!stale) this.emit(message)
        return this.run(step)
      }
      case 'pong':
        return this.run(this.tracker.pong(message.seq))
      case 'error':
        if (message.requestType === 'join') this.joinFailed(message.code)
        // This layer alone repairs a lost join, so one `join` goes out for any number of NOT_JOINED replies.
        if (message.code === 'NOT_JOINED') this.joinAgain()
        if (message.requestType === 'resync') this.resyncFailed(message.code)
        if (message.code === 'RATE_LIMITED' && message.requestType === null) {
          this.resendInFlight()
          this.retryResync(RETRY_AFTER_MS)
          // The bucket may have dropped a join that waits for its reply, never one that waits on its backoff.
          if (this.joinSent) this.retryJoin(RETRY_AFTER_MS)
        }
        if (message.requestType === 'answer') this.answerFailed(message.code)
        // A bucket RATE_LIMITED comes before parsing, so its requestType is null: it may be the dropped `next`.
        if (message.requestType === 'next' || (message.requestType === null && message.code === 'RATE_LIMITED')) {
          this.nextFailed(message.code)
        }
        break
    }
    this.emit(message)
  }

  /**
   * Repeats the outstanding resync 1 s after `RATE_LIMITED` and after a backoff wait after `UNAVAILABLE` (spec §7);
   * after any other error its snapshot deadline repeats it.
   */
  private resyncFailed(code: ErrorCode): void {
    if (code === 'RATE_LIMITED') this.retryResync(RETRY_AFTER_MS)
    else if (code === 'UNAVAILABLE') this.retryResync(backoffDelay(this.resyncFailures++, this.o.random))
  }

  /** Sends a resync and gives its `snapshot` REPLY_TIMEOUT_MS before sending it again. */
  private sendResync(lastSeq: number): void {
    this.outstandingResync = lastSeq
    this.send({ v: 1, type: 'resync', lastSeq })
    this.retryResync(REPLY_TIMEOUT_MS)
  }

  /** Sends the outstanding resync, if any, again after `wait` ms instead of at its earlier retry or deadline. */
  private retryResync(wait: number): void {
    const lastSeq = this.outstandingResync
    if (lastSeq === null) return
    this.cancel(this.resyncRetry)
    this.resyncRetry = this.after(wait, () => this.sendResync(lastSeq))
  }

  /**
   * Sends a `join` that got `UNAVAILABLE` again after the backoff (a failed join binds nothing, spec §1), also when an
   * earlier join already got `joined`, so that a `joined` always follows; any other join error is final.
   */
  private joinFailed(code: ErrorCode): void {
    this.joinSent = false
    if (code === 'UNAVAILABLE') {
      this.joining = true
      return this.retryJoin(backoffDelay(this.joinFailures++, this.o.random))
    }
    this.joining = false
    this.cancel(this.joinRetry)
  }

  /** Sends the `join` in flight, if any, again after `wait` ms instead of at its earlier retry or deadline. */
  private retryJoin(wait: number): void {
    if (!this.joining) return
    this.cancel(this.joinRetry)
    this.joinRetry = this.after(wait, () => this.rejoin())
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
      this.sendResync(resync.lastSeq)
    }
    if (resync.delayMs === 0) send()
    else this.after(resync.delayMs, send)
  }

  /**
   * Sends an unsettled answer while joined, and gives its reply REPLY_TIMEOUT_MS before sending it again; otherwise
   * the next `joined` sends it.
   */
  private sendAnswer(submissionId: string): void {
    const answer = this.unsettled.get(submissionId)
    if (answer === undefined || !this.joined) return
    this.inFlight.push(submissionId)
    this.send(answer)
    // The deadline replaces a retry still waiting. The first send keeps its place in `inFlight`: a slow reply to it
    // still arrives first.
    this.retryAnswer(submissionId, REPLY_TIMEOUT_MS)
  }

  private settle(submissionId: string): void {
    this.cancelAnswerRetry(submissionId)
    this.unsettled.delete(submissionId)
    this.unavailable.delete(submissionId)
  }

  /** Sends an unsettled answer again after `wait` ms instead of at its earlier retry or deadline. */
  private retryAnswer(submissionId: string, wait: number): void {
    this.cancelAnswerRetry(submissionId)
    const timer = this.after(wait, () => {
      this.answerRetries.delete(submissionId)
      this.sendAnswer(submissionId)
    })
    this.answerRetries.set(submissionId, timer)
  }

  private cancelAnswerRetry(submissionId: string): void {
    this.cancel(this.answerRetries.get(submissionId))
    this.answerRetries.delete(submissionId)
  }

  /** An answer error carries no `submissionId`: the server replies in order, so it belongs to the oldest in flight. */
  private answerFailed(code: ErrorCode): void {
    const submissionId = this.inFlight.shift()
    if (submissionId === undefined) return
    this.cancelAnswerRetry(submissionId)
    if (!RETRY_ON.includes(code)) return this.settle(submissionId)
    if (code === 'NOT_JOINED') return
    let wait = RETRY_AFTER_MS
    if (code === 'UNAVAILABLE') {
      const attempt = this.unavailable.get(submissionId) ?? 0
      this.unavailable.set(submissionId, attempt + 1)
      wait = backoffDelay(attempt, this.o.random)
    }
    this.retryAnswer(submissionId, wait)
  }

  /**
   * The server lost this player's join (protocol spec §7: `join`, then repeat the request). Answers and the pending
   * `next` wait, and the next `joined` resends them. A `join` already in flight is not sent again.
   */
  private joinAgain(): void {
    this.joined = false
    if (!this.joining) this.rejoin()
  }

  /**
   * A `RATE_LIMITED` without a `requestType` (the token bucket drops a frame before parsing it) may have dropped any
   * answer in flight. Resends them all after 1 s with the same `submissionId`s, which is safe because answers are
   * idempotent, and forgets the list, so that a later error is not matched to an answer that got no reply.
   */
  private resendInFlight(): void {
    const resend = this.inFlight
    this.inFlight = []
    for (const submissionId of resend) this.retryAnswer(submissionId, RETRY_AFTER_MS)
  }

  /**
   * Resends the pending `next` 1 s after `RATE_LIMITED` or after the backoff after `UNAVAILABLE`. After `NOT_JOINED`
   * it waits for the `joined` of the rejoin, which repeats it; any other error settles it.
   */
  private nextFailed(code: ErrorCode): void {
    const pending = this.pendingNext
    if (pending === null || pending.afterJoin) return
    this.cancelNextRetry()
    let wait: number
    if (code === 'RATE_LIMITED') wait = RETRY_AFTER_MS
    else if (code === 'UNAVAILABLE') wait = backoffDelay(pending.failures++, this.o.random)
    else {
      if (code === 'NOT_JOINED') pending.afterJoin = true
      else this.pendingNext = null
      return
    }
    this.nextRetry = this.after(wait, () => this.sendNext())
  }

  /** Sends the pending `next`, if any, and gives its reply REPLY_TIMEOUT_MS before sending it again. */
  private sendNext(): void {
    if (this.pendingNext === null) return
    this.send({ v: 1, type: 'next', questionIndex: this.pendingNext.questionIndex })
    this.lastNextSent = { questionIndex: this.pendingNext.questionIndex, at: this.o.now() }
    this.cancelNextRetry()
    this.nextRetry = this.after(REPLY_TIMEOUT_MS, () => this.sendNext())
  }

  /** Forgets the pending `next` and every unsettled answer, so a scheduled answer resend finds nothing to send. */
  private dropRequests(): void {
    this.cancelNextRetry()
    this.pendingNext = null
    for (const timer of this.answerRetries.values()) this.cancel(timer)
    this.answerRetries.clear()
    this.unsettled.clear()
    this.unavailable.clear()
    this.inFlight = []
  }

  private cancelNextRetry(): void {
    this.cancel(this.nextRetry)
    this.nextRetry = undefined
  }

  /** Sends on an open socket; otherwise drops the message (a reconnect resends answers, `joined` re-drives `next`). */
  private send(message: ClientMessage): void {
    if (this.open) this.socket?.send(JSON.stringify(message))
  }

  /** Restarts the 50 s liveness timer: no inbound message by then closes the link. */
  private alive(socket: QuizSocket): void {
    this.cancel(this.liveness)
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
    const status = wait !== null ? 'reconnecting' : this.backoff.exhausted ? 'failed' : 'closed'
    this.emit({ type: 'status', status, code })
    if (wait !== null) this.after(wait, () => void this.connect())
  }

  /**
   * Drops the socket and its timers: the open timeout, a pending gap resync, a resync, join, answer or `next` retry,
   * the reply deadlines, ping and liveness. Unsettled answers stay, for the next `joined`; the pending `next` goes, as `joined` re-drives it.
   */
  private disconnect(): void {
    if (this.socket !== null) this.socket.onopen = this.socket.onmessage = this.socket.onclose = null
    this.socket = null
    this.open = false
    this.joined = false
    this.joining = this.joinSent = false
    this.outstandingResync = null
    this.resyncFailures = 0
    this.joinFailures = 0
    this.inFlight = []
    this.answerRetries.clear()
    this.pendingNext = null
    this.lastNextSent = null
    for (const timer of this.timers) clearTimeout(timer)
    this.timers.clear()
    clearInterval(this.ping)
  }

  private cancel(timer: Timer | undefined): void {
    if (timer === undefined) return
    clearTimeout(timer)
    this.timers.delete(timer)
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
