// AI-ASSISTED: component tests for the intro, question and feedback screens (countdown, keys, locking, count-up, announcement), the connection pill and the error messages, driven by server frames through the quiz store.
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { ClientEvent } from '@/protocol/client'
import type { AnswerResult, Joined, Question, ServerMessage, Snapshot } from '@/protocol/types.generated'
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
const status = (value: 'reconnecting' | 'open' | 'closed', code: number | null = null) => ({ type: 'status', status: value, code }) as ClientEvent
const joined = (over: Partial<Joined> = {}): Joined => ({ v: 1, type: 'joined', atSeq: 3, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10,
  timeLimitMs: 20_000, quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0, ...over })
const snapshot = (score: number): Snapshot => ({ v: 1, type: 'snapshot', atSeq: 3, status: 'open', playerCount: 2, onlineCount: 2,
  entries: [{ rank: 1, userId: 'u1', displayName: 'Ana', score }], you: { rank: 1, score } })
const question = (questionIndex = 0, remainingMs = 20_000): Question => ({ v: 1, type: 'question', atSeq: 3, questionIndex, questionId: `q${questionIndex}`,
  prompt: 'bright', choices: ['dark', 'dim', 'shining', 'dull'], timeLimitMs: 20_000, remainingMs })
const result = (choiceIndex: number, pointsAwarded: number, over: Partial<AnswerResult> = {}): AnswerResult => ({ v: 1, type: 'answer_result', atSeq: 4,
  questionIndex: 0, submissionId: 's-1', choiceIndex, correctChoiceIndex: 2, correct: choiceIndex === 2, late: false, pointsAwarded, score: pointsAwarded, ...over })
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

function reducedMotion(): void {
  vi.spyOn(window, 'matchMedia').mockImplementation((query: string) =>
    ({ matches: query.includes('reduce'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() }) as unknown as MediaQueryList)
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

it('while the socket is reconnecting a pill says so and the choices are locked; after the snapshot the question and score are back', async () => {
  const w = await playing()
  expect(w.get('[data-test="connection"]').text()).toBe('')
  await receive(status('reconnecting', 1006))
  expect(w.get('[data-test="connection"]').attributes('role')).toBe('status')
  expect(w.get('[data-test="connection"]').text()).toBe('Reconnecting…')
  expect(w.text()).toContain('Waiting for the connection…')
  press('1')
  await choice(w, 0).trigger('click')
  expect(port.answer).not.toHaveBeenCalled()
  await receive(status('open'))
  expect(w.get('[data-test="connection"]').text()).toBe('Connecting…')
  await receive(joined({ cursor: 0, cursorOpen: true, score: 140 }))
  expect(w.get('[data-test="connection"]').text()).toBe('Updating…')
  clock = 8_000
  await receive(snapshot(140), question(0, 12_000))
  await frames(50)
  expect(w.get('[data-test="connection"]').text()).toBe('')
  expect(w.get('[data-test="ring"]').text()).toBe('12')
  expect(w.get('[data-test="score"]').text()).toBe('Score 140')
  press('4')
  expect(port.answer.mock.calls).toEqual([[0, 3]])
})

const error = (code: string, requestType: string | null = null) => ({ type: 'error', code, message: '', requestType }) as Partial<ServerMessage>

it.each([
  ['ALREADY_ANSWERED', 'That question was already answered; your first answer stands.'],
  ['QUESTION_NOT_OPEN', 'That question is closed; loading the current one.'],
  ['RATE_LIMITED', 'Too many requests; trying again in a second.'],
])('error %s: a short plain message that goes after a few seconds', async (code, text) => {
  const w = await playing()
  await receive(error(code, 'answer'))
  expect(w.get('[data-test="error"]').attributes('role')).toBe('status')
  expect(w.get('[data-test="error"]').text()).toBe(text)
  await frames(6_000)
  expect(w.get('[data-test="error"]').text()).toBe('')
})

it('SESSION_REPLACED: the card replaces the quiz, stays, takes the focus, and Use this tab joins again', async () => {
  const w = await playing()
  await receive(error('SESSION_REPLACED'))
  expect(port.stop).toHaveBeenCalled()
  expect(w.get('[role="alert"]').text()).toContain('This quiz is open in another tab.')
  expect(w.find('[data-choice="0"]').exists()).toBe(false)
  await frames(10_000)
  expect(w.find('[role="alert"]').exists()).toBe(true)
  expect(document.activeElement?.textContent?.trim()).toBe('Use this tab')
  await w.get('[role="alert"] button').trigger('click')
  expect(port.start.mock.calls).toEqual([['VOCAB-42', 'Ana'], ['VOCAB-42', 'Ana']])
  expect(w.find('[role="alert"]').exists()).toBe(false)
})

it.each(['NOT_JOINED', 'INVALID_STATE', 'INTERNAL', 'INVALID_MESSAGE'])('error %s: no message, the client recovers by itself', async (code) => {
  const w = await playing()
  await receive(error(code, 'answer'))
  expect(w.get('[data-test="error"]').text()).toBe('')
})

it('UNAVAILABLE: the pill says Server busy, retrying until the reply to the retried answer arrives, however long the backoff', async () => {
  const w = await playing()
  press('3')
  await receive(error('UNAVAILABLE', 'answer'))
  expect(w.get('[data-test="connection"]').text()).toBe('Server busy, retrying')
  expect(w.get('[data-test="error"]').text()).toBe('')
  await frames(10_000)
  expect(w.get('[data-test="connection"]').text()).toBe('Server busy, retrying')
  await receive(result(2, 133))
  expect(w.get('[data-test="connection"]').text()).toBe('')
})

it('a play screen mounted after SESSION_REPLACED shows the card with Use this tab, not an empty page', async () => {
  useQuizStore().join('VOCAB-42', 'Ana')
  await receive(joined(), snapshot(0), question(), error('SESSION_REPLACED'))
  const w = mount(PlayView, { props: { quizId: 'VOCAB-42' }, attachTo: document.body })
  wrappers.push(w)
  await nextTick()
  await nextTick()
  expect(w.get('[role="alert"]').text()).toContain('This quiz is open in another tab.')
  expect(document.activeElement?.textContent?.trim()).toBe('Use this tab')
})

it('SESSION_REPLACED after finishing: the card replaces the results and the leaderboard', async () => {
  const w = await playing({ type: 'finished', rank: 1, score: 0, playerCount: 2 })
  expect(w.text()).toContain('You finished!')
  await receive(error('SESSION_REPLACED'))
  expect(w.get('[role="alert"]').text()).toContain('This quiz is open in another tab.')
  expect(w.text()).not.toContain('You finished!')
  expect(w.find('[data-test="counts"]').exists()).toBe(false)
})

it('close 4001: the session-replaced card with Use this tab, and no Disconnected pill', async () => {
  const w = await playing()
  await receive(status('closed', 4001))
  expect(w.get('[role="alert"]').text()).toContain('This quiz is open in another tab.')
  expect(w.get('[role="alert"] button').text()).toBe('Use this tab')
  expect(w.get('[data-test="connection"]').text()).toBe('')
  expect(w.find('[data-choice="0"]').exists()).toBe(false)
})

it('UNSUPPORTED_VERSION: a blocking A new version is available card with Reload that stays', async () => {
  const w = await playing()
  await receive(error('UNSUPPORTED_VERSION'), status('closed', 1000))
  expect(port.stop).toHaveBeenCalled()
  expect(w.get('[role="alert"]').text()).toContain('A new version is available.')
  expect(w.get('[role="alert"] button').text()).toBe('Reload')
  expect(w.find('[data-choice="0"]').exists()).toBe(false)
  await frames(10_000)
  expect(w.find('[role="alert"]').exists()).toBe(true)
  expect(w.get('[data-test="connection"]').text()).toBe('')
})

it('feedback: correct, the points with the speed bonus and the total count up, an announcement, and Next question has the focus', async () => {
  const w = await playing()
  press('3')
  await receive(result(2, 133))
  expect(w.get('[data-test="points"]').text()).toBe('+0 points including a speed bonus of +33')
  expect(w.get('[data-test="score"]').text()).toBe('Score 0')
  await frames(300)
  const midway = Number(w.get('[data-test="score"]').text().replace('Score ', ''))
  expect(midway).toBeGreaterThan(0)
  expect(midway).toBeLessThan(133)
  await frames(400)
  expect(w.get('[data-test="points"]').text()).toBe('+133 points including a speed bonus of +33')
  expect(w.get('[data-test="score"]').text()).toBe('Score 133')
  expect(choice(w, 2).text()).toContain('Correct')
  expect(choice(w, 2).text()).not.toContain('Correct answer')
  expect(w.get('[data-test="announce"]').attributes('aria-live')).toBe('polite')
  expect(w.get('[data-test="announce"]').text()).toBe('Correct, plus 133 points. Score 133.')
  expect(document.activeElement?.textContent?.trim()).toBe('Next question')
  await w.get('button:focus').trigger('click')
  expect(port.next.mock.calls).toEqual([[1]])
})

it('feedback: a wrong answer is marked Wrong, the correct choice reads Correct answer, and the announcement names it', async () => {
  const w = await playing()
  press('1')
  await receive(result(0, 0))
  expect(w.get('h2').text()).toBe('Wrong')
  expect(choice(w, 0).text()).toContain('Wrong')
  expect(choice(w, 2).text()).toContain('Correct answer')
  expect(choice(w, 1).text()).toBe('dim')
  expect(w.get('[data-test="announce"]').text()).toBe('Wrong, the answer was “shining”. Score 0.')
})

it('feedback: a late answer reads Too late: 0 points; the last question offers See my result', async () => {
  const w = await playing(question(9))
  press('3')
  await receive(result(2, 0, { questionIndex: 9, late: true, score: 410 }))
  expect(w.get('[data-test="points"]').text()).toBe('Too late: 0 points')
  expect(w.get('[data-test="announce"]').text()).toBe('Too late: 0 points. Score 410.')
  expect(document.activeElement?.textContent?.trim()).toBe('See my result')
  await w.get('button:focus').trigger('click')
  expect(port.next.mock.calls).toEqual([[10]])
})

it('two late answers in a row are each announced: the region empties when the next question opens', async () => {
  const w = await playing(question(3))
  press('3')
  await receive(result(2, 0, { questionIndex: 3, late: true, score: 410 }))
  expect(w.get('[data-test="announce"]').text()).toBe('Too late: 0 points. Score 410.')
  await receive(question(4))
  expect(w.get('[data-test="announce"]').text()).toBe('')
  press('3')
  await receive(result(2, 0, { questionIndex: 4, submissionId: 's-2', late: true, score: 410 }))
  expect(w.get('[data-test="announce"]').text()).toBe('Too late: 0 points. Score 410.')
})

it('a rejoin swaps the header score at once; only an answer result counts it up', async () => {
  const w = await playing()
  await receive(joined({ cursor: 0, cursorOpen: true, score: 140 }), snapshot(140))
  expect(w.get('[data-test="score"]').text()).toBe('Score 140')
  press('3')
  await receive(result(2, 133, { score: 273 }))
  await frames(300)
  expect(w.get('[data-test="score"]').text()).not.toBe('Score 273')
  await frames(400)
  expect(w.get('[data-test="score"]').text()).toBe('Score 273')
})

it('reduced motion: the points and the total show their final value at once', async () => {
  reducedMotion()
  const w = await playing()
  press('3')
  await receive(result(2, 133))
  expect(w.get('[data-test="points"]').text()).toBe('+133 points including a speed bonus of +33')
  expect(w.get('[data-test="score"]').text()).toBe('Score 133')
})
