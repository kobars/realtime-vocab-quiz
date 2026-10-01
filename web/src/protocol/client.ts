// AI-ASSISTED: QuizClient owns the socket: connect with a fresh ticket, reconnect through Backoff, SeqTracker wiring and liveness (protocol spec §3, §7, §9).
import { Backoff, OPEN_TIMEOUT_MS } from './backoff'
import { type AuthApi, connectTicket } from './identity'
import { SeqTracker, type SeqStep } from './seq'
import type { ClientMessage, ServerMessage } from './types.generated'

export const SUBPROTOCOL = 'quiz.v1'
export const PING_INTERVAL_MS = 25_000
export const LIVENESS_TIMEOUT_MS = 50_000
export const RETRY_AFTER_MS = 1_000
/** A failed or slow open, a failed ticket request and a silent link all count as this close code. */
const DEAD_LINK = 1006

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
  | { type: 'status'; status: 'connecting' | 'open' | 'reconnecting' | 'closed'; code: number | null }

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
  private stopped = true
  private quizId = ''
  private displayName = ''
  /** The `lastSeq` of the last resync sent, repeated when the server rate-limits it. */
  private lastResync = 0
  /** Timers of the current connection; a disconnect cancels them all. */
  private readonly timers = new Set<Timer>()
  private liveness: Timer | undefined
  private ping: ReturnType<typeof setInterval> | undefined

  constructor(options: QuizClientOptions) {
    const scheme = globalThis.location?.protocol === 'https:' ? 'wss' : 'ws'
    this.o = {
      url: `${scheme}://${globalThis.location?.host}/ws`,
      socketFactory: (url, protocol) => new WebSocket(url, protocol),
      storage: sessionStorage,
      random: Math.random,
      now: () => performance.now(),
      ...options,
    }
    this.backoff = new Backoff(this.o.random)
    this.tracker = new SeqTracker(this.o.random)
  }

  start(quizId: string, displayName: string): void {
    this.quizId = quizId
    this.displayName = displayName
    this.stopped = false
    void this.connect()
  }

  next(questionIndex: number): void {
    this.send({ v: 1, type: 'next', questionIndex })
  }

  /** The user left: close with 1000 and never reconnect. */
  stop(): void {
    this.stopped = true
    this.socket?.close(1000)
    this.disconnect()
    this.emit({ type: 'status', status: 'closed', code: 1000 })
  }

  private async connect(): Promise<void> {
    this.emit({ type: 'status', status: 'connecting', code: null })
    let ticket: string
    try {
      ;({ ticket } = await connectTicket(this.o.api, this.displayName, this.o.storage))
    } catch {
      return this.closed(DEAD_LINK)
    }
    if (this.stopped) return
    const socket = this.o.socketFactory(`${this.o.url}?ticket=${encodeURIComponent(ticket)}`, SUBPROTOCOL)
    this.socket = socket
    const openTimer = this.after(OPEN_TIMEOUT_MS, () => this.kill(socket))
    socket.onopen = () => {
      clearTimeout(openTimer)
      this.emit({ type: 'status', status: 'open', code: null })
      this.ping = setInterval(() => this.send({ v: 1, type: 'ping' }), PING_INTERVAL_MS)
      this.alive(socket)
      this.send({ v: 1, type: 'join', quizId: this.quizId, displayName: this.displayName })
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
        this.run(this.tracker.joined(message.atSeq))
        break
      case 'leaderboard':
      case 'quiz_ended':
        return this.run(this.tracker.broadcast(message))
      case 'snapshot':
        this.emit(message)
        return this.run(this.tracker.snapshot(message.atSeq))
      case 'pong':
        return this.run(this.tracker.pong(message.seq))
      case 'error':
        if (message.code === 'RATE_LIMITED' && message.requestType === 'resync') {
          const lastSeq = this.lastResync
          this.after(RETRY_AFTER_MS, () => this.send({ v: 1, type: 'resync', lastSeq }))
        }
        break
    }
    this.emit(message)
  }

  /** Applies the released broadcasts in order and sends the tracker's resync, now or after its delay. */
  private run({ apply, resync }: SeqStep): void {
    for (const frame of apply) this.emit(frame)
    if (resync === null) return
    const send = () => {
      this.lastResync = resync.lastSeq
      this.send({ v: 1, type: 'resync', lastSeq: resync.lastSeq })
    }
    if (resync.delayMs === 0) send()
    else this.after(resync.delayMs, send)
  }

  private send(message: ClientMessage): void {
    this.socket?.send(JSON.stringify(message))
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

  /** Drops the socket and its timers: the open timeout, a pending gap resync, a resync retry, ping and liveness. */
  private disconnect(): void {
    if (this.socket !== null) this.socket.onopen = this.socket.onmessage = this.socket.onclose = null
    this.socket = null
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
