// AI-ASSISTED: tests for the quiz store: recorded server frames go through a real QuizClient on a fake socket, and the state is checked after each one.
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { QuizClient, type QuizSocket } from '@/protocol/client'
import type { AnswerResult, ErrorCode, Joined, Leaderboard, ProtocolError, Question, ServerMessage, Snapshot } from '@/protocol/types.generated'
import { configureQuizStore, useQuizStore } from './quiz'

class FakeSocket implements QuizSocket {
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  sent: Record<string, unknown>[] = []
  send = (data: string) => this.sent.push(JSON.parse(data) as Record<string, unknown>)
  close = () => undefined
  receive = (message: Partial<ServerMessage>) => this.onmessage?.({ data: JSON.stringify({ v: 1, ...message }) })
}

let sockets: FakeSocket[]
let clock: number
const wait = (ms: number) => vi.advanceTimersByTimeAsync(ms)
const me = { rank: 2, userId: 'u1', displayName: 'Ana', score: 0 }
const rival = { rank: 1, userId: 'u2', displayName: 'Bo', score: 140 }
const joined = (over: Partial<Joined> = {}): Joined => ({
  v: 1, type: 'joined', atSeq: 3, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 2,
  timeLimitMs: 20_000, quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0, ...over,
})
const snapshot = (atSeq: number, status: Snapshot['status'] = 'open'): Snapshot =>
  ({ v: 1, type: 'snapshot', atSeq, status, playerCount: 2, onlineCount: 2, entries: [rival, me], you: { rank: 2, score: 0 } })
const question = (questionIndex: number, remainingMs = 20_000): Question => ({ v: 1, type: 'question', atSeq: 3,
  questionIndex, questionId: `q${questionIndex}`, prompt: 'bright', choices: ['a', 'b', 'c', 'd'], timeLimitMs: 20_000, remainingMs })
const result = (questionIndex: number, submissionId: string, score: number): AnswerResult => ({ v: 1, type: 'answer_result',
  atSeq: 4, questionIndex, submissionId, choiceIndex: 1, correctChoiceIndex: 1, correct: true, late: false, pointsAwarded: score, score })
const board = (seq: number, myScore: number): Leaderboard => ({ v: 1, type: 'leaderboard', seq, rebase: false, playerCount: 3,
  onlineCount: 3, entries: [{ ...me, rank: 1, score: myScore }, { ...rival, rank: 2 }] })
const error = (code: ErrorCode, requestType: string | null): ProtocolError => ({ v: 1, type: 'error', code, message: '', requestType })

async function joinQuiz() {
  const store = useQuizStore()
  store.join('VOCAB-42', 'Ana')
  for (let i = 0; i < 3; i++) await wait(0)
  const socket = sockets.at(-1) as FakeSocket
  socket.onopen?.()
  return { store, socket }
}

async function playing() {
  const { store, socket } = await joinQuiz()
  socket.receive(joined())
  socket.receive(snapshot(3))
  return { store, socket }
}

beforeEach(() => {
  vi.useFakeTimers()
  sessionStorage.clear()
  setActivePinia(createPinia())
  sockets = []
  clock = 1_000
  let uuid = 0
  vi.spyOn(crypto, 'randomUUID').mockImplementation(() => `s-${++uuid}` as ReturnType<typeof crypto.randomUUID>)
  configureQuizStore({
    now: () => clock,
    createClient: (onEvent) => new QuizClient({
      api: { createSession: async () => ({ userId: 'u1', sessionToken: 'tok' }), createTicket: async () => 't' },
      url: 'ws://quiz.test/ws', random: () => 0.5, now: () => clock, onEvent,
      socketFactory: () => (sockets.push(new FakeSocket()), sockets.at(-1) as FakeSocket),
    }),
  })
})
afterEach(() => void (vi.useRealTimers(), vi.restoreAllMocks()))

it('join: connecting, then resyncing on joined, then joined with the standings on snapshot', async () => {
  const { store, socket } = await joinQuiz()
  expect([store.connection, store.phase]).toEqual(['connecting', 'join'])
  socket.receive(joined())
  expect([store.connection, store.phase, store.quiz?.questionCount, store.quiz?.endsAt]).toEqual(['resyncing', 'intro', 2, 601_000])
  socket.receive(snapshot(3))
  expect([store.connection, store.entries, store.playerCount, store.myRank]).toEqual(['joined', [rival, me], 2, 2])
  store.next()
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'next', questionIndex: 0 })
})

it('question: the countdown runs from remainingMs on the local clock and never blocks a late answer', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0, 15_000))
  expect([store.phase, store.question?.deadlineAt, store.msLeft(6_000), store.quiz?.cursorOpen]).toEqual(['question', 16_000, 10_000, true])
  clock = 30_000
  expect(store.msLeft()).toBe(0)
  store.answer(1)
  store.answer(2)
  expect(socket.sent.filter((message) => message.type === 'answer')).toEqual([
    { v: 1, type: 'answer', questionIndex: 0, choiceIndex: 1, submissionId: 's-1' },
  ])
  expect(store.pending).toEqual({ questionIndex: 0, choiceIndex: 1, submissionId: 's-1' })
  socket.receive(result(0, 's-1', 133))
  expect([store.phase, store.pending, store.lastResult?.pointsAwarded, store.myScore]).toEqual(['feedback', null, 133, 133])
  store.next()
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'next', questionIndex: 1 })
  socket.receive(question(1))
  store.next()
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'next', questionIndex: 2 })
  socket.receive({ type: 'finished', atSeq: 5, score: 133, rank: 1, playerCount: 2 })
  expect([store.phase, store.finished, store.myRank]).toEqual(['finished', true, 1])
})

it('leaderboard frames update the rows and my rank; a gap resyncs and the snapshot replaces the rows', async () => {
  const { store, socket } = await playing()
  socket.receive(board(4, 150))
  expect([store.myRank, store.myScore, store.playerCount, store.seq]).toEqual([1, 150, 3, 4])
  socket.receive(board(6, 290))
  expect([store.myScore, store.seq]).toEqual([150, 4])
  await wait(125)
  expect([store.connection, socket.sent.at(-1)]).toEqual(['resyncing', { v: 1, type: 'resync', lastSeq: 4 }])
  socket.receive(snapshot(6))
  expect([store.connection, store.entries, store.myRank, store.seq]).toEqual(['joined', [rival, me], 2, 6])
  socket.receive({ type: 'rank_update', atSeq: 6, rank: 210, score: 90, playerCount: 300 })
  expect([store.myRank, store.myScore, store.playerCount]).toEqual([210, 90, 300])
})

it('reconnect: resends the pending answer, does not re-serve its question, and keeps feedback on rejoin', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.onclose?.({ code: 1006 })
  expect([store.connection, store.closeCode]).toEqual(['reconnecting', 1006])
  await wait(130)
  const second = sockets.at(-1) as FakeSocket
  second.onopen?.()
  second.receive(joined({ cursor: 0, cursorOpen: true }))
  expect(second.sent.map((message) => message.type)).toEqual(['join', 'resync', 'answer'])
  expect(store.phase).toBe('question')
  second.receive(result(0, 's-1', 140))
  second.receive(snapshot(3))
  second.receive(joined({ cursor: 0, cursorOpen: false, score: 140 }))
  expect([store.phase, store.myScore]).toEqual(['feedback', 140])
})

it('a rejoin with an open question asks for it again and shows it with the stored deadline', async () => {
  const { store, socket } = await joinQuiz()
  socket.receive(joined({ cursor: 1, cursorOpen: true }))
  expect([store.phase, socket.sent.at(-1)]).toEqual(['intro', { v: 1, type: 'next', questionIndex: 1 }])
  socket.receive(question(1, 4_000))
  expect([store.phase, store.msLeft()]).toEqual(['question', 4_000])
})

it('the end: results with my final rank; a late open snapshot and finished never undo it', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.receive({ type: 'quiz_ended', seq: 4, playerCount: 2, entries: [rival, me], you: { rank: 2, score: 0 } })
  expect([store.phase, store.ended, store.pending, store.myRank, store.seq]).toEqual(['results', true, null, 2, 4])
  socket.receive(snapshot(3))
  socket.receive({ type: 'finished', atSeq: 4, score: 0, rank: 2, playerCount: 2 })
  expect([store.phase, store.entries]).toEqual(['results', [rival, me]])
  store.loadPage(0)
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'get_leaderboard', offset: 0, limit: 100 })
  socket.receive({ type: 'leaderboard_page', atSeq: 4, offset: 0, playerCount: 2, final: true, entries: [rival, me] })
  socket.receive({ type: 'leaderboard_page', atSeq: 4, offset: 1, playerCount: 2, final: true, entries: [me] })
  expect([store.allPlayers, store.pageFinal, store.pageAtSeq]).toEqual([[rival, me], true, 4])
})

it('a join after the end: the final snapshot, then QUIZ_ENDED, shows the results', async () => {
  const { store, socket } = await joinQuiz()
  socket.receive(snapshot(9, 'ended'))
  socket.receive(error('QUIZ_ENDED', 'join'))
  expect([store.phase, store.connection, store.myRank, store.lastError?.code]).toEqual(['results', 'joined', 2, 'QUIZ_ENDED'])
})

it('QUIZ_NOT_FOUND stops the client and returns to idle with the error', async () => {
  const { store, socket } = await joinQuiz()
  socket.receive(error('QUIZ_NOT_FOUND', 'join'))
  expect([store.connection, store.phase, store.lastError?.code]).toEqual(['idle', 'join', 'QUIZ_NOT_FOUND'])
})

it('ALREADY_ANSWERED unlocks the choices and rejoins on the same socket', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.receive(error('ALREADY_ANSWERED', 'answer'))
  expect([store.pending, socket.sent.at(-1)?.type]).toEqual([null, 'join'])
})

it('quiz_ended during a gap resync drops the resyncing pill, and the open snapshot that follows keeps it dropped', async () => {
  const { store, socket } = await playing()
  socket.receive(board(4, 150))
  socket.receive(board(6, 290))
  await wait(125)
  expect(store.connection).toBe('resyncing')
  socket.receive({ type: 'quiz_ended', seq: 7, playerCount: 2, entries: [rival, me], you: { rank: 2, score: 0 } })
  expect([store.phase, store.connection]).toEqual(['results', 'joined'])
  socket.receive(snapshot(6))
  expect([store.phase, store.connection]).toEqual(['results', 'joined'])
})

it('QUESTION_NOT_OPEN on an answer unlocks the choices, so the rejoin re-serves the question and a new answer goes out', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.receive(error('QUESTION_NOT_OPEN', 'answer'))
  expect([store.pending, socket.sent.at(-1)?.type]).toEqual([null, 'join'])
  socket.receive(joined({ cursor: 0, cursorOpen: true }))
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'next', questionIndex: 0 })
  socket.receive(question(0))
  store.answer(2)
  expect(socket.sent.at(-1)).toEqual({ v: 1, type: 'answer', questionIndex: 0, choiceIndex: 2, submissionId: 's-2' })
})

it('a retried answer keeps the choices locked while the server is busy', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.receive(error('UNAVAILABLE', 'answer'))
  expect(store.pending?.submissionId).toBe('s-1')
})

it('a question that arrives after quiz_ended changes nothing, and no answer goes out', async () => {
  const { store, socket } = await playing()
  socket.receive({ type: 'quiz_ended', seq: 4, playerCount: 2, entries: [rival, me], you: { rank: 2, score: 0 } })
  socket.receive(question(1))
  expect([store.phase, store.question]).toEqual(['results', null])
  store.answer(0)
  expect(socket.sent.filter((message) => message.type === 'answer')).toEqual([])
})

it('a rejoin during the feedback for the last question keeps feedback, and See my result asks for the result', async () => {
  const { store, socket } = await playing()
  socket.receive(question(1))
  store.answer(1)
  socket.receive(result(1, 's-1', 140))
  socket.onclose?.({ code: 1006 })
  await wait(130)
  const second = sockets.at(-1) as FakeSocket
  second.onopen?.()
  second.receive(joined({ cursor: 1, cursorOpen: false, finished: true, score: 140 }))
  expect([store.phase, store.finished]).toEqual(['feedback', true])
  store.next()
  expect(second.sent.at(-1)).toEqual({ v: 1, type: 'next', questionIndex: 2 })
  second.receive({ type: 'finished', atSeq: 5, score: 140, rank: 1, playerCount: 2 })
  expect(store.phase).toBe('finished')
})

it('NOT_JOINED on Next question from feedback sends one join, and the joined repeats that next', async () => {
  const { store, socket } = await playing()
  socket.receive(question(0))
  store.answer(1)
  socket.receive(result(0, 's-1', 140))
  store.next()
  socket.receive(error('NOT_JOINED', 'next'))
  expect(socket.sent.filter((message) => message.type === 'join')).toHaveLength(2)
  socket.receive(joined({ cursor: 0, cursorOpen: false, score: 140 }))
  expect(store.phase).toBe('feedback')
  expect(socket.sent.slice(-2)).toEqual([{ v: 1, type: 'resync', lastSeq: 3 }, { v: 1, type: 'next', questionIndex: 1 }])
  expect(socket.sent.filter((message) => message.type === 'join')).toHaveLength(2)
})
