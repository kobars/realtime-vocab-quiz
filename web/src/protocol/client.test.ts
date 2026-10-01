// AI-ASSISTED: tests for QuizClient: connect, reconnect, seq wiring and liveness, on a fake socket and fake timers.
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { type ClientEvent, QuizClient, type QuizSocket } from './client'
import type { ServerMessage } from './types.generated'

class FakeSocket implements QuizSocket {
  static all: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  sent: Record<string, unknown>[] = []
  closedWith: number | undefined
  constructor(readonly url: string, readonly protocol: string) { FakeSocket.all.push(this) }
  send = (data: string) => this.sent.push(JSON.parse(data) as Record<string, unknown>)
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

function start(random = () => 0) {
  let tickets = 0
  const createTicket = vi.fn(async () => `t${++tickets}`)
  const client = new QuizClient({
    api: { createSession: async () => ({ userId: 'u1', sessionToken: 'tok' }), createTicket },
    url: 'ws://quiz.test/ws',
    random,
    socketFactory: (url, protocol) => new FakeSocket(url, protocol),
    onEvent: (event) => events.push(event),
  })
  client.start('VOCAB-42', 'Ana')
  return Object.assign(client, { createTicket })
}

/** Lets the ticket request settle; returns the newest socket, opened unless told otherwise. */
async function connected(open = true) {
  for (let i = 0; i < 3; i++) await wait(0)
  const socket = FakeSocket.all.at(-1) as FakeSocket
  if (open) socket.onopen?.()
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
afterEach(() => vi.useRealTimers())

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
