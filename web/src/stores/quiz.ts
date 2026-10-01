// AI-ASSISTED: the Pinia quiz store: turns QuizClient events into the state the screens read (UI spec §3, §4).
import { defineStore } from 'pinia'
import { computed, reactive, shallowRef, toRefs } from 'vue'
import { type ClientEvent, QuizClient } from '@/protocol/client'
import { httpAuthApi } from '@/protocol/identity'
import type { AnswerResult, Entry, ErrorCode, Joined, ProtocolError, Question, ServerMessage, You } from '@/protocol/types.generated'

/** `joined` is the UI spec's `live`: the standings are current. `connecting` also covers the open socket before `joined`. */
export type Connection = 'idle' | 'connecting' | 'joined' | 'reconnecting' | 'resyncing' | 'closed'
export type Phase = 'join' | 'intro' | 'question' | 'feedback' | 'finished' | 'results'
export type QuizClientPort = Pick<QuizClient, 'start' | 'next' | 'answer' | 'rejoin' | 'getLeaderboard' | 'stop'>

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
/** Errors after which the client rejoins to read the stored `cursor` and `score` (UI spec §4.3). */
const REJOIN_ON: readonly ErrorCode[] = ['NOT_JOINED', 'QUESTION_NOT_OPEN', 'INVALID_STATE', 'ALREADY_ANSWERED']

/** The `joined` reply; `cursor` and `cursorOpen` follow later questions and results, `endsAt` is on the `now` clock. */
export type QuizInfo = Joined & { endsAt: number }
/** `deadlineAt` = arrival on the `now` clock + `remainingMs` (the server's serve time + `timeLimitMs`). */
export type CurrentQuestion = Question & { deadlineAt: number }

const initial = () => ({
  connection: 'idle' as Connection,
  closeCode: null as number | null,
  phase: 'join' as Phase,
  quiz: null as QuizInfo | null,
  question: null as CurrentQuestion | null,
  /** The answer sent for the current question and not settled yet: the choices stay locked. */
  pending: null as { questionIndex: number; choiceIndex: number; submissionId: string } | null,
  lastResult: null as AnswerResult | null,
  entries: [] as Entry[],
  playerCount: 0,
  onlineCount: 0,
  myRank: null as number | null,
  myScore: 0,
  /** Rows of "Show all players", by rank; `pageFinal` once they are the final standings. */
  allPlayers: [] as Entry[],
  pageFinal: false,
  finished: false,
  ended: false,
  lastError: null as Omit<ProtocolError, 'v' | 'type'> | null,
})

export const useQuizStore = defineStore('quiz', () => {
  const s = reactive(initial())
  const client = shallowRef<QuizClientPort | null>(null)

  const nextIndex = computed(() => {
    if (s.phase === 'question' && s.question) return s.question.questionIndex + 1
    if (s.phase === 'feedback' && s.lastResult) return s.lastResult.questionIndex + 1
    return s.quiz === null ? 0 : s.quiz.cursorOpen ? s.quiz.cursor : s.quiz.cursor + 1
  })

  /** Display only: the server decides lateness when the answer arrives. */
  function msLeft(at = deps.now()): number {
    return s.question === null ? 0 : Math.max(0, s.question.deadlineAt - at)
  }

  function join(quizId: string, displayName: string): void {
    client.value?.stop()
    Object.assign(s, initial(), { connection: 'connecting' })
    const created = deps.createClient((event) => {
      if (client.value === created) handle(event)
    })
    client.value = created
    created.start(quizId, displayName)
  }

  function answer(choiceIndex: number): void {
    const current = s.question
    if (client.value === null || s.phase !== 'question' || current === null || s.pending !== null) return
    const submissionId = client.value.answer(current.questionIndex, choiceIndex)
    s.pending = { questionIndex: current.questionIndex, choiceIndex, submissionId }
  }

  /** Start, Continue, Skip, Next question or See my result: each asks for the index the current screen implies. */
  function next(): void {
    if (s.quiz !== null && !s.ended) client.value?.next(nextIndex.value)
  }

  function loadPage(offset: number): void {
    client.value?.getLeaderboard(offset, PAGE_SIZE)
  }

  function handle(event: ClientEvent): void {
    if (event.type !== 'status') return receive(event)
    s.closeCode = event.code
    s.connection = event.status === 'open' ? 'connecting' : event.status
  }

  function receive(message: ServerMessage): void {
    switch (message.type) {
      case 'joined':
        return onJoined(message)
      case 'question':
        s.question = { ...message, deadlineAt: deps.now() + message.remainingMs }
        if (s.pending?.questionIndex !== message.questionIndex) s.pending = null
        setCursor(message.questionIndex, true)
        s.phase = 'question'
        return
      case 'answer_result':
        if (s.pending?.submissionId === message.submissionId) s.pending = null
        s.lastResult = message
        s.myScore = message.score
        setCursor(message.questionIndex, false)
        if (!s.ended) s.phase = 'feedback'
        return
      case 'finished':
        Object.assign(s, { finished: true, myRank: message.rank, myScore: message.score, playerCount: message.playerCount })
        if (!s.ended) s.phase = 'finished'
        return
      case 'leaderboard':
        return standings(message.entries, message.playerCount, message.onlineCount)
      case 'rank_update':
        Object.assign(s, { myRank: message.rank, myScore: message.score, playerCount: message.playerCount })
        return
      case 'snapshot':
        // A snapshot read before the end never undoes it (protocol §3).
        if (s.ended && message.status === 'open') return
        standings(message.entries, message.playerCount, message.onlineCount, message.you)
        if (message.status === 'ended') end()
        if (s.connection === 'resyncing') s.connection = 'joined'
        return
      case 'quiz_ended':
        standings(message.entries, message.playerCount, s.onlineCount, message.you)
        return end()
      case 'leaderboard_page':
        s.allPlayers = [...s.allPlayers.slice(0, message.offset), ...message.entries]
        s.pageFinal = message.final
        s.playerCount = message.playerCount
        return
      case 'error':
        return onError(message)
    }
  }

  function onJoined(message: Joined): void {
    s.quiz = { ...message, endsAt: deps.now() + message.quizRemainingMs }
    Object.assign(s, { myScore: message.score, finished: message.finished, connection: 'resyncing' })
    if (s.ended) return
    if (message.finished) s.phase = 'finished'
    else if (message.cursorOpen) {
      // Ask for the open question again, unless an answer to it is on its way (`next` re-serves closed questions too).
      if (s.pending?.questionIndex !== message.cursor) client.value?.next(message.cursor)
      if (s.phase !== 'question') s.phase = 'intro'
    } else if (!(s.phase === 'feedback' && s.lastResult?.questionIndex === message.cursor)) s.phase = 'intro'
  }

  function onError({ code, message, requestType }: ProtocolError): void {
    s.lastError = { code, message, requestType }
    if (code === 'QUIZ_NOT_FOUND') {
      client.value?.stop()
      client.value = null
      s.connection = 'idle'
    } else if (code === 'QUIZ_ENDED') {
      if (s.connection === 'connecting') s.connection = 'joined'
      end()
    } else if (code === 'UNSUPPORTED_VERSION') client.value?.stop()
    else if (REJOIN_ON.includes(code) && !s.ended) {
      if (code === 'ALREADY_ANSWERED') s.pending = null
      client.value?.rejoin()
    }
  }

  function standings(rows: Entry[], players: number, online: number, you?: You | null): void {
    Object.assign(s, { entries: rows, playerCount: players, onlineCount: online })
    const mine = you ?? rows.find((row) => row.userId === s.quiz?.userId)
    if (mine) Object.assign(s, { myRank: mine.rank, myScore: mine.score })
  }

  function setCursor(cursor: number, open: boolean): void {
    if (s.quiz !== null) Object.assign(s.quiz, { cursor, cursorOpen: open })
  }

  function end(): void {
    Object.assign(s, { ended: true, pending: null, phase: 'results' })
  }

  return { ...toRefs(s), nextIndex, msLeft, join, answer, next, loadPage }
})
