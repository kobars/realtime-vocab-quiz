// AI-ASSISTED: tests for QuizClient: connect, reconnect, seq wiring, liveness and answer retries, on a fake socket and fake timers.
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { type ClientEvent, QuizClient, type QuizClientOptions, type QuizSocket, SNAPSHOT_TIMEOUT_MS } from './client'
import { httpAuthApi, IDENTITY_TIMEOUT_MS } from './identity'
import type { ServerMessage } from './types.generated'

class FakeSocket implements QuizSocket {
  static all: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  sent: Record<string, unknown>[] = []
  closedWith: number | undefined
  opened = false
  constructor(readonly url: string, readonly protocol: string) { FakeSocket.all.push(this) }
  /** Like the browser WebSocket, `send` throws while the socket is still connecting. */
  send = (data: string) => {
    if (!this.opened) throw new DOMException('still connecting', 'InvalidStateError')
    this.sent.push(JSON.parse(data) as Record<string, unknown>)
  }
  open = () => {
    this.opened = true
    this.onopen?.()
  }
  close = (code = 1005) => (this.closedWith = code)
  types = () => this.sent.map((message) => message.type)
  receive = (message: Partial<ServerMessage>) => this.onmessage?.({ data: JSON.stringify({ v: 1, ...message }) })
  drop = (code = 1006) => this.onclose?.({ code })
}

const sockets = () => FakeSocket.all.length
const board = (seq: number) => ({ type: 'leaderboard', seq, rebase: false }) as const
const joined = (atSeq = 0) => ({ type: 'joined', atSeq }) as const
const resync = (lastSeq: number) => ({ v: 1, type: 'resync', lastSeq })
const wait = (ms: number) => vi.advanceTimersByTimeAsync(ms)
let events: ClientEvent[]

function start(random = () => 0, options: Partial<QuizClientOptions> = {}) {
  let tickets = 0
  const createTicket = vi.fn(async () => `t${++tickets}`)
  const client = new QuizClient({
    api: { createSession: async () => ({ userId: 'u1', sessionToken: 'tok' }), createTicket },
    url: 'ws://quiz.test/ws',
    random,
    socketFactory: (url, protocol) => new FakeSocket(url, protocol),
    onEvent: (event) => events.push(event),
    ...options,
  })
  client.start('VOCAB-42', 'Ana')
  return Object.assign(client, { createTicket })
}

/** Lets the ticket request settle; returns the newest socket, opened unless told otherwise. */
async function connected(open = true) {
  for (let i = 0; i < 3; i++) await wait(0)
  const socket = FakeSocket.all.at(-1) as FakeSocket
  if (open) socket.open()
  return socket
}

async function joinedSocket() {
  const socket = await connected()
  socket.receive(joined())
  socket.receive({ type: 'snapshot', atSeq: 0, status: 'open' })
  return socket
}

beforeEach(() => {
  vi.useFakeTimers()
  sessionStorage.clear()
  FakeSocket.all = []
  events = []
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('opens /ws with a fresh ticket and the quiz.v1 subprotocol, then joins', async () => {
  start()
  const socket = await connected()
  expect([socket.url, socket.protocol]).toEqual(['ws://quiz.test/ws?ticket=t1', 'quiz.v1'])
  expect(socket.sent).toEqual([{ v: 1, type: 'join', quizId: 'VOCAB-42', displayName: 'Ana' }])
})

it('treats an open slower than 5 s, or a failed ticket request, as 1006', async () => {
  const client = start()
  client.createTicket.mockRejectedValueOnce(new Error('offline'))
  const slow = await connected(false)
  expect(events).toContainEqual({ type: 'status', status: 'reconnecting', code: 1006 })
  await wait(4_999)
  expect([slow.closedWith, sockets()]).toEqual([undefined, 1])
  // Fake timers run a 0 ms timeout made inside another timer 1 ms later.
  await wait(2)
  await connected(false)
  expect([slow.closedWith, sockets(), FakeSocket.all[1]?.url]).toEqual([1005, 2, 'ws://quiz.test/ws?ticket=t2'])
})

it('a session request that never answers fails after 5 s and reconnects with backoff, instead of hanging on connecting', async () => {
  const fetchFn = vi.fn<typeof fetch>(() => new Promise(() => undefined))
  const client = start(() => 0, { api: httpAuthApi('/api', fetchFn) })
  await wait(4_999)
  expect(events).toEqual([{ type: 'status', status: 'connecting', code: null }])
  await wait(1)
  expect(events.at(-1)).toEqual({ type: 'status', status: 'reconnecting', code: 1006 })
  await wait(1)
  expect([fetchFn.mock.calls.length, sockets()]).toEqual([2, 0])
  // The tab shares one session request per storage: let the second one time out too, so later tests start clean.
  client.stop()
  await wait(IDENTITY_TIMEOUT_MS)
})

it('gives up with status failed after 10 connects in a row without a joined, and opens no more sockets', async () => {
  start()
  for (let i = 0; i < 9; i++) {
    ;(await connected(i % 2 === 0)).drop()
    expect(events.at(-1)).toEqual({ type: 'status', status: 'reconnecting', code: 1006 })
  }
  ;(await connected()).drop()
  expect(events.at(-1)).toEqual({ type: 'status', status: 'failed', code: 1006 })
  await wait(60_000)
  expect(sockets()).toBe(10)
})

it('waits 5 s plus the backoff after 1013', async () => {
  start(() => 0.5)
  ;(await connected()).drop(1013)
  await wait(5_124)
  expect(sockets()).toBe(1)
  await wait(1)
  await connected(false)
  expect(sockets()).toBe(2)
})

it.each([1000, 1008, 4001])('never reconnects after %i', async (code) => {
  start()
  ;(await connected()).drop(code)
  await wait(60_000)
  expect(sockets()).toBe(1)
  expect(events.at(-1)).toEqual({ type: 'status', status: 'closed', code })
})

it('tells Backoff about the join, so 10 s joined resets the attempts', async () => {
  start(() => 0.999999)
  ;(await connected()).drop()
  await wait(249)
  ;(await connected()).drop()
  await wait(499)
  const socket = await joinedSocket()
  await wait(10_000)
  socket.drop()
  await wait(248)
  expect(sockets()).toBe(3)
  await wait(1)
  await connected(false)
  expect(sockets()).toBe(4)
})

it('stop() closes with 1000 and never reconnects', async () => {
  const client = start()
  const socket = await joinedSocket()
  client.stop()
  await wait(60_000)
  expect([socket.closedWith, sockets()]).toEqual([1000, 1])
})

it('sends one resync with the last applied seq on every joined', async () => {
  start()
  const first = await joinedSocket()
  first.receive(board(1))
  expect(first.sent[1]).toEqual(resync(0))
  expect(events.filter((event) => event.type === 'leaderboard')).toMatchObject([{ seq: 1 }])
  first.drop()
  const second = await connected()
  second.receive(joined(4))
  expect(second.sent.slice(1)).toEqual([resync(1)])
  // The link drops before the snapshot: joined.atSeq never moves the last applied seq.
  second.drop()
  const third = await connected()
  third.receive(joined(5))
  expect(third.sent.slice(1)).toEqual([resync(1)])
})

it('sends a gap resync after its delay', async () => {
  start(() => 0.5)
  const socket = await joinedSocket()
  socket.receive(board(1))
  socket.receive(board(3))
  await wait(124)
  expect(socket.types()).toEqual(['join', 'resync'])
  await wait(1)
  expect(socket.sent.at(-1)).toEqual(resync(1))
})

it('cancels a pending gap resync on a disconnect', async () => {
  const randoms = [0.9, 0] // a 225 ms gap wait, then no reconnect wait
  start(() => randoms.shift() ?? 0)
  const first = await joinedSocket()
  first.receive(board(2))
  first.drop()
  const second = await connected()
  await wait(1_000)
  expect([first.types(), second.types()]).toEqual([['join', 'resync'], ['join']])
})

it('retries a rate-limited resync after 1 s', async () => {
  start()
  const socket = await connected()
  socket.receive(joined(2))
  socket.receive({ type: 'error', code: 'RATE_LIMITED', requestType: 'resync' })
  await wait(999)
  expect(socket.types()).toEqual(['join', 'resync'])
  await wait(1)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(0)])
})

it('retries a resync after UNAVAILABLE with backoff, until the snapshot', async () => {
  start(() => 0.5)
  const socket = await connected()
  socket.receive(joined(2))
  socket.receive({ type: 'error', code: 'UNAVAILABLE', requestType: 'resync' })
  await wait(124)
  expect(socket.types()).toEqual(['join', 'resync'])
  await wait(1)
  socket.receive({ type: 'error', code: 'UNAVAILABLE', requestType: 'resync' })
  await wait(249)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(0)])
  await wait(1)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(0), resync(0)])
  socket.receive({ type: 'snapshot', atSeq: 2, status: 'open' })
  socket.receive(board(3))
  expect(events.filter((event) => event.type === 'leaderboard')).toMatchObject([{ seq: 3 }])
})

/** The gateway's token bucket drops the frame before parsing it, so its error names no request. */
const bucketDrop = { type: 'error', code: 'RATE_LIMITED', message: 'message dropped: rate limited', requestType: null } as const
const leaderboards = () => events.filter((event) => event.type === 'leaderboard').map((event) => event.seq)

it('sends the outstanding resync again 1 s after a RATE_LIMITED that names no request, while frames keep arriving', async () => {
  start()
  const socket = await joinedSocket()
  socket.receive(board(1))
  socket.receive(board(3))
  socket.receive(bucketDrop)
  socket.receive(board(4))
  socket.receive({ type: 'pong', seq: 4 })
  await wait(999)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(1)])
  await wait(1)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(1), resync(1)])
  socket.receive({ type: 'snapshot', atSeq: 3, status: 'open' })
  expect(leaderboards()).toEqual([1, 4])
})

it('sends a resync again each time its snapshot does not arrive in time, until it does', async () => {
  start()
  const socket = await joinedSocket()
  socket.receive(board(2))
  const resyncs = () => socket.sent.filter((message) => message.type === 'resync').length
  for (let seq = 3; seq <= 7; seq++) {
    await wait(SNAPSHOT_TIMEOUT_MS / 5)
    socket.receive(board(seq))
    socket.receive({ type: 'pong', seq })
  }
  expect(resyncs()).toBe(3)
  await wait(SNAPSHOT_TIMEOUT_MS)
  expect(resyncs()).toBe(4)
  socket.receive({ type: 'snapshot', atSeq: 2, status: 'open' })
  await wait(3 * SNAPSHOT_TIMEOUT_MS)
  expect([resyncs(), leaderboards()]).toEqual([4, [3, 4, 5, 6, 7]])
})

it('resyncs when the broadcast that a pong announced has not arrived 1 s later', async () => {
  start()
  const socket = await joinedSocket()
  socket.receive({ type: 'pong', seq: 1 })
  socket.receive(board(1))
  await wait(1_000)
  socket.receive({ type: 'pong', seq: 2 })
  await wait(999)
  expect(socket.types()).toEqual(['join', 'resync'])
  await wait(1)
  expect(socket.sent.slice(1)).toEqual([resync(0), resync(1)])
})

it('emits a snapshot read before the end after quiz_ended no more, and applies a status ended one', async () => {
  start()
  const socket = await joinedSocket()
  socket.receive({ type: 'quiz_ended', seq: 1 })
  const ended = events.length
  socket.receive({ type: 'snapshot', atSeq: 0, status: 'open' })
  expect(events.slice(ended)).toEqual([])
  socket.receive({ type: 'snapshot', atSeq: 1, status: 'ended' })
  expect(events.slice(ended)).toMatchObject([{ type: 'snapshot', atSeq: 1, status: 'ended' }])
})

it('drops next() while the socket is still connecting instead of throwing', async () => {
  const client = start()
  const socket = await connected(false)
  expect(() => client.next(0)).not.toThrow()
  socket.open()
  socket.receive(joined())
  socket.receive({ type: 'snapshot', atSeq: 0, status: 'open' })
  socket.receive({ type: 'error', code: 'RATE_LIMITED', requestType: null } as Partial<ServerMessage>)
  await wait(5_000)
  expect(socket.types()).toEqual(['join', 'resync'])
})

it('opens one socket after start, stop, start while the first ticket request is pending', async () => {
  const client = start()
  client.stop()
  client.start('VOCAB-42', 'Ana')
  const socket = await connected()
  expect([sockets(), socket.types()]).toEqual([1, ['join']])
})

it('ignores a stale ticket failure after start, stop, start', async () => {
  let fail: (error: Error) => void = () => {}
  const client = start()
  client.createTicket.mockImplementationOnce(() => new Promise((_, reject) => (fail = reject)))
  client.stop()
  // The first start() asks for its ticket only after the session exists, so this stale request is the one that fails.
  client.start('VOCAB-42', 'Ana')
  const socket = await connected()
  fail(new Error('offline'))
  await wait(0)
  expect([sockets(), socket.closedWith]).toEqual([1, undefined])
  expect(events).not.toContainEqual(expect.objectContaining({ status: 'reconnecting' }))
})

it('falls back to the default url when url is undefined', async () => {
  start(() => 0, { url: undefined })
  const socket = await connected()
  expect(socket.url).toBe(`ws://${location.host}/ws?ticket=t1`)
})

it('never reads sessionStorage when a storage is given', async () => {
  vi.spyOn(globalThis, 'sessionStorage', 'get').mockImplementation(() => {
    throw new DOMException('blocked', 'SecurityError')
  })
  start(() => 0, { storage: localStorage })
  expect(sockets()).toBe(0)
  await connected()
  expect(sockets()).toBe(1)
})

it('sends an app ping every 25 s, and reconnects after 50 s without an inbound message', async () => {
  start()
  const socket = await joinedSocket()
  await wait(24_999)
  expect(socket.types()).not.toContain('ping')
  await wait(1)
  socket.receive({ type: 'pong', seq: 0 })
  await wait(25_000)
  expect(socket.types().filter((type) => type === 'ping')).toHaveLength(2)
  await wait(24_999)
  expect(socket.closedWith).toBeUndefined()
  await wait(2)
  await connected(false)
  expect([socket.closedWith, sockets()]).toEqual([1005, 2])
})

const answerMsg = (submissionId: string, questionIndex = 0, choiceIndex = 2) => ({
  v: 1,
  type: 'answer',
  questionIndex,
  choiceIndex,
  submissionId,
})
const answers = (socket: FakeSocket) => socket.sent.filter((message) => message.type === 'answer')
const answerError = (code: string) => ({ type: 'error', code, requestType: 'answer' }) as Partial<ServerMessage>
const result = (submissionId: string) => ({ type: 'answer_result', submissionId }) as Partial<ServerMessage>

function uuids(...ids: string[]) {
  const spy = vi.spyOn(crypto, 'randomUUID')
  for (const id of ids) spy.mockReturnValueOnce(id as ReturnType<typeof crypto.randomUUID>)
  return spy
}

it('answer() makes one submissionId, returns it and sends it at once while joined', async () => {
  const spy = uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  expect(client.answer(0, 2)).toBe('s-1')
  expect(spy).toHaveBeenCalledTimes(1)
  expect(socket.sent.at(-1)).toEqual(answerMsg('s-1'))
})

it('holds an answer made before joined, and sends it after the resync that follows joined', async () => {
  uuids('s-1')
  const client = start()
  const socket = await connected()
  client.answer(0, 2)
  expect(socket.types()).toEqual(['join'])
  socket.receive(joined(3))
  expect(socket.sent.slice(1)).toEqual([resync(0), answerMsg('s-1')])
})

it('resends unsettled answers with the same submissionId after each reconnect, until answer_result', async () => {
  uuids('s-1', 's-2')
  const client = start()
  const first = await joinedSocket()
  client.answer(0, 2)
  client.answer(1, 3)
  first.receive(result('s-1'))
  first.drop()
  const second = await connected()
  expect(answers(second)).toEqual([])
  second.receive(joined())
  expect(second.sent.slice(1)).toEqual([resync(0), answerMsg('s-2', 1, 3)])
  second.receive(result('s-2'))
  second.drop()
  const third = await connected()
  third.receive(joined())
  expect(answers(third)).toEqual([])
})

it('sends the same answer again 1 s after RATE_LIMITED', async () => {
  uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  socket.receive(answerError('RATE_LIMITED'))
  await wait(999)
  expect(answers(socket)).toHaveLength(1)
  await wait(1)
  expect(answers(socket)).toEqual([answerMsg('s-1'), answerMsg('s-1')])
})

it('sends the same answer again after a full-jitter backoff that grows with each UNAVAILABLE', async () => {
  uuids('s-1')
  const client = start(() => 0.5)
  const socket = await joinedSocket()
  client.answer(0, 2)
  // Waits of floor(0.5 × 250 × 2^attempt): 125, 250 and 500 ms.
  for (const delay of [125, 250, 500]) {
    const sent = answers(socket).length
    socket.receive(answerError('UNAVAILABLE'))
    await wait(delay - 1)
    expect(answers(socket)).toHaveLength(sent)
    await wait(1)
    expect(answers(socket)).toHaveLength(sent + 1)
  }
  expect(answers(socket).every((message) => message.submissionId === 's-1')).toBe(true)
})

const rateLimited = { type: 'error', code: 'RATE_LIMITED', requestType: null } as Partial<ServerMessage>

it('resends every answer in flight 1 s after a RATE_LIMITED that names no request', async () => {
  uuids('s-1', 's-2')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.answer(1, 3)
  socket.receive(rateLimited)
  await wait(999)
  expect(answers(socket)).toHaveLength(2)
  await wait(1)
  expect(answers(socket).map((message) => message.submissionId)).toEqual(['s-1', 's-2', 's-1', 's-2'])
})

it('settles only its own answer with a final error that follows a RATE_LIMITED that names no request', async () => {
  uuids('s-1', 's-2')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.answer(1, 3)
  // s-1 was dropped, so the next reply is for s-2: it settles nothing, since the list no longer says whose it is.
  socket.receive(rateLimited)
  socket.receive(answerError('ALREADY_ANSWERED'))
  await wait(1_000)
  // The resends go out as s-1, s-2: the next final error is s-1's and settles s-1 only.
  socket.receive(answerError('ALREADY_ANSWERED'))
  socket.drop()
  const next = await connected()
  next.receive(joined())
  expect(answers(next)).toEqual([answerMsg('s-2', 1, 3)])
})

it('keeps an answer after NOT_JOINED, joins again and resends it after the next joined', async () => {
  uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  socket.receive(answerError('NOT_JOINED'))
  expect(socket.types()).toEqual(['join', 'resync', 'answer', 'join'])
  await wait(5_000)
  expect(answers(socket)).toHaveLength(1)
  socket.receive(joined())
  expect(socket.types().slice(4)).toEqual(['resync', 'answer'])
  expect(answers(socket)).toEqual([answerMsg('s-1'), answerMsg('s-1')])
})

it('matches an answer error to the oldest answer in flight on that socket', async () => {
  uuids('s-1', 's-2')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.answer(1, 3)
  socket.receive(answerError('RATE_LIMITED'))
  await wait(1_000)
  expect(answers(socket).map((message) => message.submissionId)).toEqual(['s-1', 's-2', 's-1'])
  // s-2 is now the oldest in flight: the final error drops it, and s-1 stays unsettled.
  socket.receive(answerError('QUESTION_NOT_OPEN'))
  socket.drop()
  const next = await connected()
  next.receive(joined())
  expect(answers(next)).toEqual([answerMsg('s-1')])
})

it.each(['ALREADY_ANSWERED', 'QUESTION_NOT_OPEN', 'INVALID_MESSAGE', 'QUIZ_ENDED'])(
  'drops an answer after the final error %s',
  async (code) => {
    uuids('s-1')
    const client = start()
    const socket = await joinedSocket()
    client.answer(0, 2)
    socket.receive(answerError(code))
    await wait(5_000)
    expect(answers(socket)).toHaveLength(1)
    socket.drop()
    const next = await connected()
    next.receive(joined())
    expect(answers(next)).toEqual([])
  },
)

it('cancels a pending answer retry on a disconnect and resends the answer once after the reconnect', async () => {
  uuids('s-1')
  const client = start()
  const first = await joinedSocket()
  client.answer(0, 2)
  first.receive(answerError('RATE_LIMITED'))
  first.drop()
  const second = await connected()
  second.receive(joined())
  await wait(2_000)
  expect([answers(first), answers(second)]).toEqual([[answerMsg('s-1')], [answerMsg('s-1')]])
})

it('ignores errors of other requests when matching answers', async () => {
  uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  socket.receive({ type: 'error', code: 'INVALID_STATE', requestType: 'next' })
  socket.drop()
  const next = await connected()
  next.receive(joined())
  expect(answers(next)).toEqual([answerMsg('s-1')])
})

it('forgets the answers in flight on a dropped socket when matching errors on the next one', async () => {
  uuids('s-1', 's-2')
  const client = start()
  const first = await joinedSocket()
  client.answer(0, 2)
  first.drop()
  const second = await connected()
  second.receive(joined())
  client.answer(1, 3)
  second.receive(answerError('RATE_LIMITED'))
  second.receive(answerError('QUESTION_NOT_OPEN'))
  await wait(1_000)
  expect(answers(second).map((message) => message.submissionId)).toEqual(['s-1', 's-2', 's-1'])
})

const nexts = (socket: FakeSocket) => socket.sent.filter((message) => message.type === 'next').map((m) => m.questionIndex)
const overload = (code: string, requestType: string | null = 'next') =>
  ({ type: 'error', code, requestType }) as Partial<ServerMessage>
const question = (questionIndex: number) => ({ type: 'question', questionIndex }) as Partial<ServerMessage>

it.each(['next', null])('sends the same next again 1 s after RATE_LIMITED with requestType %s, until question', async (type) => {
  const client = start()
  const socket = await joinedSocket()
  client.next(2)
  socket.receive(overload('RATE_LIMITED', type))
  await wait(999)
  expect(nexts(socket)).toEqual([2])
  await wait(1)
  expect(nexts(socket)).toEqual([2, 2])
  socket.receive(question(1))
  socket.receive(overload('RATE_LIMITED', null))
  await wait(1_000)
  expect(nexts(socket)).toEqual([2, 2, 2])
  socket.receive(question(2))
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([2, 2, 2])
})

it('sends the same next again after the growing backoff after UNAVAILABLE, until finished', async () => {
  const client = start(() => 0.5)
  const socket = await joinedSocket()
  client.next(10)
  socket.receive(overload('UNAVAILABLE'))
  await wait(124)
  expect(nexts(socket)).toEqual([10])
  await wait(1)
  socket.receive(overload('UNAVAILABLE'))
  await wait(249)
  expect(nexts(socket)).toEqual([10, 10])
  await wait(1)
  expect(nexts(socket)).toEqual([10, 10, 10])
  socket.receive({ type: 'finished' } as Partial<ServerMessage>)
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([10, 10, 10])
})

it.each(['INVALID_STATE', 'QUIZ_ENDED'])('stops retrying a next after the final error %s', async (code) => {
  const client = start()
  const socket = await joinedSocket()
  client.next(3)
  socket.receive(overload(code))
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([3])
})

it('joins again after a next gets NOT_JOINED, and repeats that next once after the joined', async () => {
  const client = start()
  const socket = await joinedSocket()
  client.next(3)
  socket.receive(overload('NOT_JOINED'))
  expect(socket.types().slice(-2)).toEqual(['next', 'join'])
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([3])
  socket.receive(joined())
  expect(socket.types().slice(-2)).toEqual(['resync', 'next'])
  socket.receive(overload('RATE_LIMITED', null))
  await wait(1_000)
  socket.receive(question(3))
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([3, 3, 3])
})

it('repeats no next after NOT_JOINED when a newer next replaced it before the joined', async () => {
  const client = start()
  const socket = await joinedSocket()
  client.next(3)
  socket.receive(overload('NOT_JOINED'))
  client.next(2)
  socket.receive(joined())
  await wait(5_000)
  expect(nexts(socket)).toEqual([3, 2])
})

it('sends one join when an answer and a next in flight both get NOT_JOINED, then repeats both', async () => {
  uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.next(1)
  socket.receive(answerError('NOT_JOINED'))
  socket.receive(overload('NOT_JOINED'))
  expect(socket.types().filter((type) => type === 'join')).toHaveLength(2)
  socket.receive(joined())
  expect(socket.types().slice(-3)).toEqual(['resync', 'answer', 'next'])
})

it('sends no second join on NOT_JOINED while a rejoin is in flight, and still resends the answer after it', async () => {
  uuids('s-1')
  const client = start()
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.rejoin()
  socket.receive(answerError('NOT_JOINED'))
  expect(socket.types().filter((type) => type === 'join')).toHaveLength(2)
  socket.receive(joined())
  expect(answers(socket)).toEqual([answerMsg('s-1'), answerMsg('s-1')])
})

it('records no pending next for a next() dropped between sockets', async () => {
  const client = start()
  ;(await joinedSocket()).drop()
  client.next(5)
  await wait(1_000)
  const second = await connected()
  second.receive(joined())
  second.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(second)).toEqual([])
})

it('drops the pending next and its retry on quiz_ended', async () => {
  const client = start(() => 0.5)
  const socket = await joinedSocket()
  client.next(5)
  socket.receive(overload('UNAVAILABLE'))
  socket.receive({ type: 'quiz_ended', seq: 1 } as Partial<ServerMessage>)
  socket.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect(nexts(socket)).toEqual([5])
})

it('drops unsettled answers and their retries on quiz_ended', async () => {
  uuids('s-1', 's-2')
  const client = start(() => 0.5)
  const socket = await joinedSocket()
  client.answer(0, 2)
  client.answer(1, 3)
  socket.receive(answerError('UNAVAILABLE'))
  socket.receive({ type: 'quiz_ended', seq: 1 } as Partial<ServerMessage>)
  socket.receive(rateLimited)
  await wait(5_000)
  expect(answers(socket)).toEqual([answerMsg('s-1'), answerMsg('s-2', 1, 3)])
})

it('retries only the newest next when the player asks again before the retry', async () => {
  const client = start()
  const socket = await joinedSocket()
  client.next(1)
  socket.receive(overload('RATE_LIMITED'))
  client.next(2)
  await wait(5_000)
  expect(nexts(socket)).toEqual([1, 2])
})

it('cancels a pending next retry on a disconnect and leaves the next request to joined', async () => {
  const client = start()
  const first = await joinedSocket()
  client.next(4)
  first.receive(overload('RATE_LIMITED'))
  first.drop()
  const second = await connected()
  second.receive(joined())
  second.receive(overload('RATE_LIMITED', null))
  await wait(5_000)
  expect([nexts(first), nexts(second)]).toEqual([[4], []])
})

it('sends a join that got UNAVAILABLE again after the growing backoff, then resends the unsettled answer', async () => {
  uuids('s-1')
  const client = start(() => 0.5)
  const first = await joinedSocket()
  client.answer(0, 2)
  first.drop()
  await wait(125)
  const second = await connected()
  second.receive({ type: 'error', code: 'UNAVAILABLE', requestType: 'join' })
  await wait(124)
  expect(second.types()).toEqual(['join'])
  await wait(1)
  second.receive({ type: 'error', code: 'UNAVAILABLE', requestType: 'join' })
  second.receive({ type: 'pong', seq: 0 })
  await wait(249)
  expect(second.types()).toEqual(['join', 'join'])
  await wait(1)
  second.receive(joined())
  expect(second.types()).toEqual(['join', 'join', 'join', 'resync', 'answer'])
  expect(answers(second)).toEqual([answerMsg('s-1')])
})
