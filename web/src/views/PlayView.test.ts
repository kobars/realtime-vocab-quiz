// AI-ASSISTED: component tests for the intro and question screens (countdown, keys, locking), driven by server frames through the quiz store.
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { ClientEvent } from '@/protocol/client'
import type { Joined, Question, ServerMessage, Snapshot } from '@/protocol/types.generated'
import { configureQuizStore, type QuizClientPort, useQuizStore } from '@/stores/quiz'
import PlayView from './PlayView.vue'

let emit: (event: ClientEvent) => void
let clock = 0
let port: Record<keyof QuizClientPort, ReturnType<typeof vi.fn>>
const wrappers: VueWrapper[] = []

async function receive(...messages: (Partial<ServerMessage> | ClientEvent)[]) {
  for (const message of messages) emit((message.type === 'status' ? message : { v: 1, ...message }) as ClientEvent)
  await nextTick()
  await nextTick()
}
const status = (value: 'reconnecting' | 'open', code: number | null = null) => ({ type: 'status', status: value, code }) as ClientEvent
const joined = (over: Partial<Joined> = {}): Joined => ({ v: 1, type: 'joined', atSeq: 3, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10,
  timeLimitMs: 20_000, quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0, ...over })
const snapshot = (score: number): Snapshot => ({ v: 1, type: 'snapshot', atSeq: 3, status: 'open', playerCount: 2, onlineCount: 2,
  entries: [{ rank: 1, userId: 'u1', displayName: 'Ana', score }], you: { rank: 1, score } })
const question = (questionIndex = 0, remainingMs = 20_000): Question => ({ v: 1, type: 'question', atSeq: 3, questionIndex, questionId: `q${questionIndex}`,
  prompt: 'bright', choices: ['dark', 'dim', 'shining', 'dull'], timeLimitMs: 20_000, remainingMs })
const choice = (w: VueWrapper, i: number) => w.get(`[data-choice="${i}"]`)
const press = (key: string) => (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
const frames = (ms: number) => vi.advanceTimersByTimeAsync(ms)

async function playing(...first: Partial<ServerMessage>[]) {
  useQuizStore().join('VOCAB-42', 'Ana')
  await receive(joined(), snapshot(0), ...(first.length > 0 ? first : [question()]))
  const wrapper = mount(PlayView, { props: { quizId: 'VOCAB-42' }, attachTo: document.body })
  wrappers.push(wrapper)
  await nextTick()
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
  clock = 0
  setActivePinia(createPinia())
  port = { start: vi.fn(), next: vi.fn(), answer: vi.fn(() => 's-1'), rejoin: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() }
  configureQuizStore({ now: () => clock, createClient: (onEvent) => ((emit = onEvent), port as unknown as QuizClientPort) })
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('the ring counts down on the monotonic clock, whatever the wall clock says; at zero an answer already sent stays pending', async () => {
  vi.setSystemTime(new Date('2099-01-01T00:00:00Z'))
  const w = await playing()
  expect(w.get('[data-test="ring"]').text()).toBe('20')
  expect(w.get('[data-test="progress"]').text()).toBe('Question 1 of 10')
  clock = 7_500
  await frames(50)
  expect(w.get('[data-test="ring"]').attributes('aria-label')).toBe('13 seconds left')
  press('2')
  clock = 21_000
  await frames(50)
  expect(w.get('[data-test="time-up"]').text()).toContain("Time's up: an answer now scores 0.")
  expect(choice(w, 1).text()).toContain('Checking…')
  expect(w.find('[data-test="time-up"] button').exists()).toBe(false)
})

it('keys 1–4 answer once: the choices lock with Checking… while it is pending, and focus starts on the prompt', async () => {
  const w = await playing()
  expect(document.activeElement?.textContent?.trim()).toBe('bright')
  press('3')
  press('1')
  await choice(w, 0).trigger('click')
  expect(port.answer.mock.calls).toEqual([[0, 2]])
  expect(choice(w, 2).text()).toContain('Checking…')
  expect(choice(w, 0).attributes('aria-disabled')).toBe('true')
})

it('intro: Start has the focus and asks for question 0; after a rejoin on a closed question it reads Continue', async () => {
  const w = await playing({ type: 'leaderboard', seq: 4, rebase: false, playerCount: 2, onlineCount: 2, entries: [] })
  expect(document.activeElement?.textContent?.trim()).toBe('Start')
  expect(w.text()).toContain('10 questions, 20 seconds each.')
  await w.get('button:focus').trigger('click')
  expect(port.next.mock.calls).toEqual([[0]])
  await receive(joined({ cursor: 2, cursorOpen: false }))
  expect(w.get('button:focus').text()).toBe('Continue')
})

it('while the socket is reconnecting the choices are locked; once joined again a key answers', async () => {
  const w = await playing()
  await receive(status('reconnecting', 1006))
  expect(w.text()).toContain('Waiting for the connection…')
  press('1')
  await choice(w, 0).trigger('click')
  expect(port.answer).not.toHaveBeenCalled()
  await receive(status('open'), joined({ cursor: 0, cursorOpen: true }))
  clock = 8_000
  await receive(snapshot(0), question(0, 12_000))
  await frames(50)
  expect(w.get('[data-test="ring"]').text()).toBe('12')
  press('4')
  expect(port.answer.mock.calls).toEqual([[0, 3]])
})
