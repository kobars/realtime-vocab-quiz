// AI-ASSISTED: component tests for the leaderboard rows, the live panel and "Show all players" paging, driven by server frames through the quiz store.
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { ClientEvent } from '@/protocol/client'
import type { Entry, ServerMessage } from '@/protocol/types.generated'
import { configureQuizStore, type QuizClientPort, useQuizStore } from '@/stores/quiz'
import LeaderboardPanel from './LeaderboardPanel.vue'
import LeaderboardRows from './LeaderboardRows.vue'

let emit: (event: ClientEvent) => void
let port: { [K in keyof QuizClientPort]: ReturnType<typeof vi.fn> }
const wrappers: VueWrapper[] = []

const row = (rank: number, score: number, userId = `p${rank}`): Entry => ({ rank, userId, displayName: `Player ${rank}`, score })
const top = (n: number, from = 1) => Array.from({ length: n }, (_, i) => row(from + i, 1_500 - (from + i) * 10))
const me = (rank: number, score: number): Entry => ({ rank, userId: 'u1', displayName: 'Ana', score })

async function receive(...messages: Partial<ServerMessage>[]) {
  for (const message of messages) emit({ v: 1, ...message } as ServerMessage)
  await nextTick()
}
const board = (seq: number, entries: Entry[], playerCount = 300) =>
  ({ type: 'leaderboard', seq, rebase: false, playerCount, onlineCount: playerCount - 10, entries }) as const
const page = (atSeq: number, offset: number, entries: Entry[], final = false) =>
  ({ type: 'leaderboard_page', atSeq, offset, playerCount: 300, final, entries }) as const

async function joinedStore() {
  const store = useQuizStore()
  store.join('VOCAB-42', 'Ana')
  await receive(
    { type: 'joined', atSeq: 3, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10, timeLimitMs: 20_000,
      quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0 },
    { type: 'snapshot', atSeq: 3, status: 'open', playerCount: 3, onlineCount: 2, entries: [row(1, 140), me(2, 0), row(3, 0)], you: { rank: 2, score: 0 } },
  )
  return store
}
// Test Utils stubs TransitionGroup by default; the real one renders the list element and runs the moves.
const options = { attachTo: document.body, global: { stubs: { TransitionGroup: false } } }
const track = <W extends VueWrapper>(wrapper: W): W => (wrappers.push(wrapper), wrapper)
const render = (component: typeof LeaderboardPanel) => track(mount(component, options))
const rows = (entries: Entry[]) => track(mount(LeaderboardRows, { ...options, props: { entries } }))
const ranks = (w: VueWrapper) => w.findAll('li').map((li) => li.find('span').text())
const sent = () => port.getLeaderboard.mock.calls

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  port = { start: vi.fn(), next: vi.fn(), answer: vi.fn(() => 's-1'), rejoin: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() }
  configureQuizStore({ now: () => 0, createClient: (onEvent) => ((emit = onEvent), port as unknown as QuizClientPort) })
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.useRealTimers()
})

it('renders rows in rank order, at most 50, and ties keep equal scores with distinct ranks', () => {
  const tied = [row(3, 90), row(2, 140, 'b'), row(1, 140, 'a'), ...top(197, 4)]
  const w = rows(tied)
  expect(w.findAll('li')).toHaveLength(50)
  expect(ranks(w).slice(0, 3)).toEqual(['#1', '#2', '#3'])
  expect(w.findAll('li').slice(0, 2).map((li) => li.findAll('span')[2]?.text())).toEqual(['140', '140'])
})

it('keeps each row element across 5 updates per second, and skips FLIP when more than 20 rows move', async () => {
  let entries = top(50)
  const w = rows(entries)
  const element = (userId: string) => w.find(`[data-user="${userId}"]`).element
  const before = element('p10')
  for (let tick = 0; tick < 25; tick++) {
    // Two neighbours swap places each 200 ms tick.
    const i = tick % 49
    entries = entries.map((e, j) => (j === i ? { ...entries[i + 1], rank: i + 1 } : j === i + 1 ? { ...entries[i], rank: i + 2 } : e)) as Entry[]
    await w.setProps({ entries })
  }
  expect([w.findAll('li').length, element('p10')]).toEqual([50, before])
  expect(w.find('ol').attributes('data-flip')).toBe('true')
  await w.setProps({ entries: [...entries].reverse().map((e, i) => ({ ...e, rank: i + 1 })) })
  expect(w.find('ol').attributes('data-flip')).toBe('false')
})

it('highlights my row, shows the counts, and pins my row from rank_update outside the top 50', async () => {
  const store = await joinedStore()
  const w = render(LeaderboardPanel)
  expect(w.find('[aria-current="true"]').text()).toContain('Ana (you)')
  expect(w.find('[data-test="counts"]').text()).toBe('3 players · 2 online')
  expect(w.find('[data-test="pinned"]').exists()).toBe(false)
  await receive(board(4, top(50)), { type: 'rank_update', atSeq: 4, rank: 120, score: 310, playerCount: 300 })
  const pinned = w.find('[data-test="pinned"]').findAll('span').map((span) => span.text())
  expect([store.myRank, pinned]).toEqual([120, ['#120', 'Ana (you)', '310']])
  // My old row fades out (it keeps its leave class until the transition ends).
  expect(w.find('[aria-current="true"]:not(.lb-leave-active)').exists()).toBe(false)
  await receive(board(5, [me(1, 2_000), ...top(49, 2)]))
  expect(w.find('[data-test="pinned"]').exists()).toBe(false)
})

it('pages through get_leaderboard, shows the page atSeq and reloads it at most once per second while scores move', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  await w.find('button').trigger('click')
  expect(sent()).toEqual([[0, 100]])
  await receive(page(7, 0, top(100)))
  expect(w.find('[data-test="page-seq"]').text()).toBe('As of update 7')
  await w.findAll('button').find((b) => b.text() === 'Next')?.trigger('click')
  expect(sent().at(-1)).toEqual([100, 100])
  await receive(page(7, 100, top(100, 101)))
  expect(w.text()).toContain('Players 101–200 of 300')
  // Three frames in 400 ms: one reload of the open page, a second after the last load.
  await receive(board(8, top(50)))
  await vi.advanceTimersByTimeAsync(200)
  await receive(board(9, top(50)), board(10, top(50)))
  await vi.advanceTimersByTimeAsync(799)
  expect(sent()).toHaveLength(2)
  await vi.advanceTimersByTimeAsync(1)
  expect(sent()).toEqual([[0, 100], [100, 100], [100, 100]])
  const moved = top(100, 101).map((e, i) => (i === 0 ? { ...e, score: 9_999 } : e))
  await receive(page(10, 100, moved))
  expect([w.find('[data-test="page-seq"]').text(), w.find('[data-user="p101"]').text()]).toEqual(['As of update 10', expect.stringContaining('9999')])
  await vi.advanceTimersByTimeAsync(5_000)
  expect(sent()).toHaveLength(3)
  await w.find('section section').trigger('keydown', { key: 'Escape' })
  expect(w.find('button').text()).toBe('Show all players')
})

it('a final page is never reloaded', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  await w.find('button').trigger('click')
  await receive(page(9, 0, top(100), true), board(10, top(50)))
  await vi.advanceTimersByTimeAsync(3_000)
  expect([sent(), w.find('[data-test="page-seq"]').text()]).toEqual([[[0, 100]], 'Final standings'])
})
