// AI-ASSISTED: the Pinia quiz store: turns QuizClient events into the state the screens read (UI spec §3, §4).
import { defineStore } from 'pinia'
import { computed, reactive, shallowRef, toRefs } from 'vue'
import { type ClientEvent, QuizClient, RETRY_ANSWER_ON } from '@/protocol/client'
import { httpAuthApi } from '@/protocol/identity'
import type { AnswerResult, Entry, ErrorCode, Joined, ProtocolError, Question, ServerMessage, You } from '@/protocol/types.generated'

/** `joined` is the UI spec's `live`: the standings are current. `connecting` also covers the open socket before `joined`. */
export type Connection = 'idle' | 'connecting' | 'joined' | 'reconnecting' | 'resyncing' | 'closed'
export type Phase = 'join' | 'intro' | 'question' | 'feedback' | 'finished' | 'results'
/**
 * The UI spec's `blocked` state, which only the player can leave: another tab took the session, the client is outdated,
 * the server closed with a policy violation (1008), or the client gave up after 10 connects without a `joined`.
 */
export type Blocked = 'replaced' | 'version' | 'policy' | 'unreachable'
export type QuizClientPort = Pick<QuizClient, 'start' | 'next' | 'answer' | 'rejoin' | 'refresh' | 'getLeaderboard' | 'stop'>

export interface QuizStoreDeps {
  createClient: (onEvent: (event: ClientEvent) => void) => QuizClientPort
  /** A monotonic clock in ms; deadlines are measured on it, never on the wall clock (protocol §6). */
  now: () => number
}

const deps: QuizStoreDeps = {
  createClient: (onEvent) => new QuizClient({ api: httpAuthApi(), onEvent }),
  now: () => performance.now(),
}

/** Replaces the socket client or the clock, for tests. */
export function configureQuizStore(overrides: Partial<QuizStoreDeps>): void {
  Object.assign(deps, overrides)
}

export const PAGE_SIZE = 100
/**
 * Errors after which the store rejoins to read the stored `cursor` and `score` (UI spec §4.3). `NOT_JOINED` is not
 * here: the client sends that `join` itself and repeats the request.
 */
const REJOIN_ON: readonly ErrorCode[] = ['QUESTION_NOT_OPEN', 'INVALID_STATE', 'ALREADY_ANSWERED']
/** The requests the client sends again after `UNAVAILABLE`, and the server message that replies to each. */
const RETRIED_BY_REPLY: Partial<Record<ServerMessage['type'], string>> = {
  joined: 'join', answer_result: 'answer', question: 'next', finished: 'next', snapshot: 'resync',
}
const RETRIED_ON_UNAVAILABLE: readonly (string | null)[] = Object.values(RETRIED_BY_REPLY)
/** The final close codes that block the screen (protocol §7): 4001, another tab took the session; 1008, a policy violation. */
const BLOCKED_BY_CLOSE: Partial<Record<number, Blocked>> = { 4001: 'replaced', 1008: 'policy' }

/** The `joined` reply; `cursor` and `cursorOpen` follow later questions and results, `endsAt` is on the `now` clock. */
export type QuizInfo = Joined & { endsAt: number }
/**
 * `deadlineAt` = the time the client last sent the `next` for this question on the `now` clock (its arrival, if it sent
 * none) + `remainingMs`, so a slow reply shortens the countdown by the round trip instead of showing time the server will
 * not honour, and a resend after a dropped `next` restarts that offset (protocol §6).
 */
export type CurrentQuestion = Question & { deadlineAt: number }
/** A `leaderboard_page`: `rows` from rank `offset + 1`, read from the standings at `atSeq`; `final` once they are the final standings. */
export interface StandingsPage { offset: number; atSeq: number; final: boolean; rows: Entry[] }

const initial = () => ({
  connection: 'idle' as Connection,
  closeCode: null as number | null,
  phase: 'join' as Phase,
  /** The quiz ID sent in the last `join`; it stays after a join to an ended quiz, which binds no `quiz`. */
  quizId: null as string | null,
  quiz: null as QuizInfo | null,
  question: null as CurrentQuestion | null,
  /** The answer sent for the current question and not settled yet: the choices stay locked. */
  pending: null as { questionIndex: number; choiceIndex: number; submissionId: string } | null,
  lastResult: null as AnswerResult | null,
  entries: [] as Entry[],
  /** The `seq` of the standings in `entries` (a `leaderboard`, `snapshot` or `quiz_ended`); -1 before the first. */
  seq: -1,
  playerCount: 0,
  onlineCount: 0,
  myRank: null as number | null,
  myScore: 0,
  /** The `atSeq` of the last `answer_result`: standings at or before it were built before that answer was scored. */
  answeredAtSeq: -1,
  /** Counts the standings applied as a full replacement (`snapshot`, `rebase: true`), which swap in one step (UI spec §5.1). */
  replacements: 0,
  /** The last page of "Show all players". */
  page: null as StandingsPage | null,
  finished: false,
  ended: false,
  lastError: null as Omit<ProtocolError, 'v' | 'type'> | null,
  blocked: null as Blocked | null,
  /** The request type that got `UNAVAILABLE` and is being retried, until a reply to it arrives (UI spec §3.7). */
  busy: null as string | null,
})

export const useQuizStore = defineStore('quiz', () => {
  const s = reactive(initial())
  const client = shallowRef<QuizClientPort | null>(null)
  /** The arguments of the last join, for `retry`: a blocked screen may have no `quiz` yet. */
  let lastJoin: { quizId: string; displayName: string } | null = null

  const nextIndex = computed(() => {
    if (s.phase === 'question' && s.question) return s.question.questionIndex + 1
    if (s.phase === 'feedback' && s.lastResult) return s.lastResult.questionIndex + 1
    return s.quiz === null ? 0 : s.quiz.cursorOpen ? s.quiz.cursor : s.quiz.cursor + 1
  })

  /** Display only: the server decides lateness when the answer arrives. */
  function msLeft(at = deps.now()): number {
    return s.question === null ? 0 : Math.max(0, s.question.deadlineAt - at)
  }

  /** Display only: the time until the quiz window closes, from `quizRemainingMs`. */
  const quizMsLeft = (at = deps.now()): number => (s.quiz === null ? 0 : Math.max(0, s.quiz.endsAt - at))

  function join(quizId: string, displayName: string): void {
    lastJoin = { quizId, displayName }
    client.value?.stop()
    Object.assign(s, initial(), { connection: 'connecting', quizId })
    const created = deps.createClient((event) => {
      if (client.value === created) handle(event)
    })
    client.value = created
    created.start(quizId, displayName)
  }

  /** Joins the last quiz again with a new client, so the connect attempts count from zero ("Use this tab", "Try again"). */
  function retry(): void {
    if (lastJoin !== null) join(lastJoin.quizId, lastJoin.displayName)
  }

  function answer(choiceIndex: number): void {
    const current = s.question
    if (client.value === null || s.phase !== 'question' || current === null || s.pending !== null) return
    const submissionId = client.value.answer(current.questionIndex, choiceIndex)
    s.pending = { questionIndex: current.questionIndex, choiceIndex, submissionId }
  }

  /** Start, Continue, Skip, Next question or See my result: each asks for the index the current screen implies. */
  const next = (): void => (s.quiz === null || s.ended ? undefined : client.value?.next(nextIndex.value))
  const loadPage = (offset: number): void => client.value?.getLeaderboard(offset, PAGE_SIZE)

  function handle(event: ClientEvent): void {
    if (event.type !== 'status') return receive(event)
    s.closeCode = event.code
    s.connection = event.status === 'open' ? 'connecting' : event.status === 'failed' ? 'closed' : event.status
    // A gap resync keeps the socket; any other status means a new or no socket, which drops the retry.
    if (event.status !== 'resyncing') s.busy = null
    if (event.status === 'failed') s.blocked = 'unreachable'
    else if (event.status === 'closed' && event.code !== null) s.blocked = BLOCKED_BY_CLOSE[event.code] ?? s.blocked
  }

  function receive(message: Exclude<ClientEvent, { type: 'status' }>): void {
    if (s.busy !== null && (RETRIED_BY_REPLY[message.type] === s.busy || message.type === 'quiz_ended')) s.busy = null
    switch (message.type) {
      case 'joined':
        return onJoined(message)
      case 'question': {
        // A reply built before the end that arrives after quiz_ended never undoes it (protocol §3).
        if (s.ended) return
        const { askedMsAgo = 0, ...question } = message
        s.question = { ...question, deadlineAt: deps.now() - askedMsAgo + message.remainingMs }
        if (s.pending?.questionIndex !== message.questionIndex) s.pending = null
        setCursor(message.questionIndex, true)
        s.phase = 'question'
        return
      }
      case 'answer_result':
        if (s.pending?.submissionId === message.submissionId) s.pending = null
        // A reply read before the end never changes the final standings either (protocol §3).
        if (s.ended) return
        Object.assign(s, { lastResult: message, myScore: message.score, answeredAtSeq: message.atSeq, phase: 'feedback' })
        setCursor(message.questionIndex, false)
        return
      case 'finished':
        if (s.ended) return
        Object.assign(s, { finished: true, phase: 'finished', myRank: message.rank, myScore: message.score, playerCount: message.playerCount })
        return
      case 'leaderboard':
        standings(message.seq, message.entries, message.playerCount, message.onlineCount, undefined, message.rebase)
        return
      case 'rank_update':
        if (!s.ended) Object.assign(s, { myRank: message.rank, myScore: ownScore(message.atSeq, message.score), playerCount: message.playerCount })
        return
      case 'snapshot':
        // A snapshot read before the end never undoes it (protocol §3).
        if (s.ended && message.status === 'open') return
        // A snapshot's `you: null` means this user is not a player, so there is no rank or score to show.
        if (!standings(message.atSeq, message.entries, message.playerCount, message.onlineCount, message.you, true)) {
          Object.assign(s, { myRank: null, myScore: 0 })
        }
        if (message.status === 'ended') end()
        if (s.connection === 'resyncing') s.connection = 'joined'
        return
      case 'quiz_ended': {
        const known = standings(message.seq, message.entries, message.playerCount, s.onlineCount, message.you)
        end()
        // Here `you: null` for a player outside the entries means the node could not read the rank, so the last one
        // shown may be stale: a resync after the end gets the final snapshot, with `you`.
        if (!known && s.quiz !== null) client.value?.refresh()
        return
      }
      case 'leaderboard_page':
        // A page read before the end never shows after it: only the final standings do.
        if (s.ended && !message.final) return
        s.page = { offset: message.offset, atSeq: message.atSeq, final: message.final, rows: message.entries }
        s.playerCount = message.playerCount
        return
      case 'error':
        return onError(message)
    }
  }

  function onJoined(message: Joined): void {
    s.quiz = { ...message, endsAt: deps.now() + message.quizRemainingMs }
    Object.assign(s, { finished: message.finished, connection: 'resyncing' })
    if (s.ended) return
    s.myScore = message.score
    // Feedback for the answered, closed cursor stays, even on the last question (UI spec §4.2).
    if (!message.cursorOpen && s.phase === 'feedback' && s.lastResult?.questionIndex === message.cursor) return
    if (message.finished) s.phase = 'finished'
    else if (message.cursorOpen) {
      // Ask for the open question again, unless an answer to it is on its way (`next` re-serves closed questions too).
      if (s.pending?.questionIndex !== message.cursor) client.value?.next(message.cursor)
      if (s.phase !== 'question') s.phase = 'intro'
    } else s.phase = 'intro'
  }

  function onError({ code, message, requestType }: ProtocolError): void {
    s.lastError = { code, message, requestType }
    if (code === 'UNAVAILABLE') s.busy = RETRIED_ON_UNAVAILABLE.includes(requestType) ? requestType : s.busy
    else if (requestType === s.busy) s.busy = null
    // The client settles every answer error but these, so the choices unlock.
    if (requestType === 'answer' && !RETRY_ANSWER_ON.includes(code)) s.pending = null
    if (code === 'QUIZ_NOT_FOUND') idle()
    else if (code === 'QUIZ_ENDED') {
      if (s.connection === 'connecting') s.connection = 'joined'
      end()
    } else if (code === 'UNSUPPORTED_VERSION' || code === 'SESSION_REPLACED') {
      s.blocked = code === 'SESSION_REPLACED' ? 'replaced' : 'version'
      client.value?.stop()
    }
    // A failed first join binds nothing (protocol §1): back to idle, which also stops the client's retry of it.
    else if (requestType === 'join' && s.quiz === null) idle()
    else if (REJOIN_ON.includes(code) && !s.ended) client.value?.rejoin()
  }

  /** Drops the client for good, so the join screen can start a new one. */
  function idle(): void {
    client.value?.stop()
    client.value = null
    s.connection = 'idle'
  }

  /**
   * Applies the standings; returns whether they gave my rank and score, from `you` or my row in `rows`. `you` is read
   * when the message is built, so it can be newer than the rows; my row then shows its rank and score, like the header.
   */
  function standings(seq: number, rows: Entry[], players: number, online: number, you?: You | null, replace = false): boolean {
    const row = rows.find((entry) => entry.userId === s.quiz?.userId)
    const mine = you ?? row
    // Only live `leaderboard` rows (no `you` field) can predate my last answer; a snapshot or the final standings set it.
    if (mine) Object.assign(s, { myRank: mine.rank, myScore: you === undefined ? ownScore(seq, mine.score) : mine.score })
    Object.assign(s, { seq, entries: row ? placeMe(rows, row) : rows, playerCount: players, onlineCount: online })
    if (replace) s.replacements += 1
    return mine !== undefined
  }

  /**
   * `rows` with my row at my current rank and score. When `you` holds a rank other than my row's, my row moves there and
   * the rows between shift by one, so the ranks stay unique; a rank past the last row leaves my row to the pinned row.
   */
  function placeMe(rows: Entry[], row: Entry): Entry[] {
    const rank = s.myRank ?? row.rank
    if (rank === row.rank) return row.score === s.myScore ? rows : rows.map((entry) => (entry === row ? { ...row, score: s.myScore } : entry))
    const [low, high, shift] = rank < row.rank ? [rank, row.rank, 1] : [row.rank, rank, -1]
    const others = rows.filter((entry) => entry !== row)
      .map((entry) => (entry.rank >= low && entry.rank <= high ? { ...entry, rank: entry.rank + shift } : entry))
    if (!rows.some((entry) => entry.rank >= rank)) return others
    const at = others.findIndex((entry) => entry.rank > rank)
    others.splice(at === -1 ? others.length : at, 0, { ...row, rank, score: s.myScore })
    return others
  }

  /**
   * My score from standings at `seq`: those at or before my last answer's `atSeq` were built before it was scored, so
   * they never lower the score it gave (protocol §3). `you` and `joined` are read fresh and set it directly.
   */
  const ownScore = (seq: number, score: number): number => (seq <= s.answeredAtSeq ? Math.max(score, s.myScore) : score)

  const setCursor = (cursor: number, open: boolean): void => void (s.quiz && Object.assign(s.quiz, { cursor, cursorOpen: open }))
  /**
   * The end drops the pending answer and the resync pill: a snapshot read before it never arrives (UI spec §4.3).
   * It also drops a live "Show all players" page, so the results list waits for a final one.
   */
  function end(): void {
    Object.assign(s, { ended: true, pending: null, phase: 'results', page: s.page?.final ? s.page : null })
    if (s.connection === 'resyncing') s.connection = 'joined'
  }

  return { ...toRefs(s), nextIndex, msLeft, quizMsLeft, join, retry, answer, next, loadPage, now: (): number => deps.now() }
})
