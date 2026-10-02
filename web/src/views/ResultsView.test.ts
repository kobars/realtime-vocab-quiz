// AI-ASSISTED: component tests for the finished and results screens, the podium (order, medals, the one-shot rise), the top 10 with my pinned row, "Show all players" in their place, and an ended quiz with no players, driven by server frames through the quiz store.
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import LeaderboardPanel from '@/components/leaderboard/LeaderboardPanel.vue'
import type { ClientEvent } from '@/protocol/client'
import type { Entry, ServerMessage } from '@/protocol/types.generated'
import { configureQuizStore, type QuizClientPort, useQuizStore } from '@/stores/quiz'
import ResultsView from './ResultsView.vue'

let emit: (event: ClientEvent) => void
let clock = 0
let getLeaderboard: ReturnType<typeof vi.fn>
const wrappers: VueWrapper[] = []

const row = (rank: number, score: number, userId = `p${rank}`): Entry => ({ rank, userId, displayName: `Player ${rank}`, score })
const top = (n: number, from = 1) => Array.from({ length: n }, (_, i) => row(from + i, 1_500 - (from + i) * 10))
const me = (rank: number, score: number): Entry => ({ rank, userId: 'u1', displayName: 'Ana', score })
const steps = (w: VueWrapper) => w.findAll('[data-rank]').map((step) => step.attributes('data-rank'))

async function receive(...messages: Partial<ServerMessage>[]) {
  for (const message of messages) emit({ v: 1, ...message } as ClientEvent)
  await nextTick()
}

async function join(snapshot = true) {
  useQuizStore().join('VOCAB-42', 'Ana')
  await receive({ type: 'joined', atSeq: 3, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10, timeLimitMs: 20_000,
    quizRemainingMs: 252_000, cursor: -1, cursorOpen: false, finished: false, score: 0 })
  if (snapshot) {
    await receive({ type: 'snapshot', atSeq: 3, status: 'open', playerCount: 3, onlineCount: 2, entries: [row(1, 140), me(2, 0), row(3, 0)],
      you: { rank: 2, score: 0 } })
  }
}

const render = () => {
  const wrapper = mount(ResultsView, { attachTo: document.body, global: { stubs: { TransitionGroup: false } } })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
  clock = 0
  setActivePinia(createPinia())
  getLeaderboard = vi.fn()
  const port = { start: vi.fn(), next: vi.fn(), answer: vi.fn(() => 's-1'), rejoin: vi.fn(), refresh: vi.fn(), getLeaderboard, stop: vi.fn() }
  configureQuizStore({ now: () => clock, createClient: (onEvent) => ((emit = onEvent), port as unknown as QuizClientPort) })
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.useRealTimers()
})

it('before the end: my score, a provisional rank with the time left, and the live board', async () => {
  await join()
  await receive({ type: 'finished', atSeq: 5, score: 410, rank: 2, playerCount: 3 })
  const w = render()
  await nextTick()
  expect(w.find('[data-test="my-result"]').text()).toMatch(/You finished!.*410 points.*Rank #2 of 3.*Provisional.*until the quiz ends in 4:12/s)
  expect(document.activeElement?.textContent?.trim()).toBe('You finished!')
  expect(w.findComponent(LeaderboardPanel).exists()).toBe(true)
  clock = 61_000
  await vi.advanceTimersByTimeAsync(1_000)
  expect(w.find('[data-test="my-result"]').text()).toContain('ends in 3:11')
})

it('when the quiz ends: the provisional mark goes, my final rank shows and focus moves to the results heading', async () => {
  await join()
  await receive({ type: 'finished', atSeq: 5, score: 410, rank: 2, playerCount: 3 })
  const w = render()
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 3, entries: [row(1, 500), me(2, 410), row(3, 90)], you: { rank: 2, score: 410 } })
  await nextTick()
  expect(w.text()).not.toContain('Provisional')
  expect(w.findComponent(LeaderboardPanel).exists()).toBe(false)
  expect(w.find('[data-test="my-result"]').text()).toMatch(/You placed #2 of 3.*410 points/s)
  expect(document.activeElement?.textContent?.trim()).toBe('Final results')
})

it('results: the podium (second, first, third), the rest of the top 10 and the same paging', async () => {
  await join()
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 60, entries: [...top(3), me(4, 900), ...top(46, 5)], you: { rank: 4, score: 900 } })
  const w = render()
  // Read in rank order; first place moves to the middle with CSS only.
  expect(steps(w)).toEqual(['1', '2', '3'])
  expect(w.findAll('[data-rank]').map((step) => step.classes().find((c) => c.startsWith('order-')))).toEqual(['order-2', 'order-1', 'order-3'])
  expect(w.find('[data-rank="1"]').text()).toMatch(/Player 1.*1490.*1/s)
  expect(w.find('[data-test="my-result"]').text()).toContain('You placed #4 of 60')
  expect(w.findAll('ol').at(-1)?.findAll('li')).toHaveLength(7)
  expect(w.find('[data-test="pinned"]').exists()).toBe(false)
  await w.findAll('button').find((b) => b.text() === 'Show all players')?.trigger('click')
  expect(getLeaderboard.mock.calls).toEqual([[0, 100]])
})

it('the podium medals are decorative; each step keeps its rank as text and dark text on its fill', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 3, entries: top(3), you: null })
  const w = render()
  for (const rank of ['1', '2', '3']) {
    const step = w.get(`[data-rank="${rank}"]`)
    const [medal, , , base] = step.findAll('span')
    expect(medal?.attributes('aria-hidden')).toBe('true')
    expect(medal?.text()).toMatch(/\p{Extended_Pictographic}/u)
    expect(base?.text()).toBe(rank)
    expect(base?.classes()).toContain(rank === '1' ? 'text-night' : 'text-foreground')
  }
})

it('the podium rises once, third place first, only behind motion-safe', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 3, entries: top(3), you: null })
  const w = render()
  const motion = (rank: string) => w.get(`[data-rank="${rank}"]`).classes().filter((c) => /animate-|rise-delay-/.test(c))
  expect(['3', '2', '1'].map(motion)).toEqual([
    ['motion-safe:animate-rise', 'rise-delay-0'],
    ['motion-safe:animate-rise', 'rise-delay-1'],
    ['motion-safe:animate-rise', 'rise-delay-2'],
  ])
})

it('a podium with fewer than 3 players shows only its steps, and a viewer with you: null sees no own result', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 2, entries: [row(1, 300), row(2, 100)], you: null })
  const w = render()
  expect(steps(w)).toEqual(['1', '2'])
  expect(w.find('[data-rank="2"]').classes()).toContain('order-1')
  expect(w.find('[data-test="my-result"]').exists()).toBe(false)
  expect(w.findAll('ol').at(-1)?.findAll('li')).toHaveLength(0)
})

it('results from an ended snapshot of more than 10 players list only ranks 4 to 10 under the podium', async () => {
  await join(false)
  await receive({ type: 'snapshot', atSeq: 9, status: 'ended', playerCount: 60, onlineCount: 0, entries: [...top(3), me(4, 900), ...top(56, 5)],
    you: { rank: 4, score: 900 } })
  const w = render()
  const ranks = (w.findAll('ol').at(-1)?.findAll('li') ?? []).map((li) => li.text().match(/#(\d+)/)?.[1])
  expect(ranks).toHaveLength(7)
  expect([ranks[0], ranks.at(-1)]).toEqual(['4', '10'])
})

it('finished: my score and my rank are polite live regions, and the rank is announced at most once every 5 s', async () => {
  await join()
  await receive({ type: 'finished', atSeq: 5, score: 410, rank: 2, playerCount: 3 })
  const w = render()
  const live = () => w.findAll('[aria-live="polite"][aria-atomic="true"]').map((region) => region.text())
  expect(live()).toEqual(['410 points', 'Rank 2 of 3'])
  await receive({ type: 'rank_update', rank: 3, score: 410, playerCount: 4 })
  expect(live()[1]).toBe('Rank 3 of 4')
  await receive({ type: 'rank_update', rank: 4, score: 410, playerCount: 5 })
  await receive({ type: 'rank_update', rank: 5, score: 410, playerCount: 6 })
  await vi.advanceTimersByTimeAsync(4_999)
  expect(live()[1]).toBe('Rank 3 of 4')
  await vi.advanceTimersByTimeAsync(1)
  expect(live()[1]).toBe('Rank 5 of 6')
  await vi.advanceTimersByTimeAsync(5_000)
  await receive({ type: 'rank_update', rank: 6, score: 410, playerCount: 7 })
  expect(live()[1]).toBe('Rank 6 of 7')
})

it('after the end, "Show all players" never shows a live page from before the end', async () => {
  await join()
  const live = [me(1, 410), ...top(11, 2)]
  const final = [row(1, 500), me(2, 410), ...top(10, 3)]
  await receive({ type: 'finished', atSeq: 5, score: 410, rank: 1, playerCount: 12 })
  const w = render()
  await w.findAll('button').find((b) => b.text() === 'Show all players')?.trigger('click')
  await receive({ type: 'leaderboard_page', atSeq: 7, offset: 0, final: false, playerCount: 12, entries: live })
  expect(w.find('[data-test="page-range"]').text()).toBe('Players 1–12 of 12')
  await receive({ type: 'quiz_ended', seq: 8, playerCount: 12, entries: final, you: { rank: 2, score: 410 } })
  await w.findAll('button').find((b) => b.text() === 'Show all players')?.trigger('click')
  expect(w.find('[data-test="page-status"]').text()).toBe('Loading players…')
  expect(w.find('section[aria-label="Show all players"]').findAll('li')).toHaveLength(0)
  await receive({ type: 'leaderboard_page', atSeq: 7, offset: 0, final: false, playerCount: 12, entries: live })
  expect(w.find('section[aria-label="Show all players"]').findAll('li')).toHaveLength(0)
  await receive({ type: 'leaderboard_page', atSeq: 8, offset: 0, final: true, playerCount: 12, entries: final })
  expect(w.find('[data-test="page-range"]').text()).toBe('Players 1–12 of 12 · Final standings')
})

it('"Show all players" shows each player once, never under a list that already holds the same rows', async () => {
  await join(false)
  const final = [...top(3), me(4, 900), ...top(18, 5)]
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 22, entries: final, you: { rank: 4, score: 900 } })
  const w = render()
  await w.findAll('button').find((b) => b.text() === 'Show all players')?.trigger('click')
  await receive({ type: 'leaderboard_page', atSeq: 6, offset: 0, final: true, playerCount: 22, entries: final })
  for (const userId of ['p5', 'u1', 'p22']) expect(w.findAll(`li[data-user="${userId}"]`)).toHaveLength(1)
})

it('results: my row outside the top 10 is pinned under ranks 4 to 10, and "Show all players" takes their place until it closes', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 30, entries: [...top(14), me(15, 1_340), ...top(15, 16)], you: { rank: 15, score: 1_340 } })
  const w = render()
  expect(w.get('[data-test="pinned"]').text()).toMatch(/#15.*Ana \(you\).*1340/s)
  expect(w.findAll('li[data-user="u1"]')).toHaveLength(0)
  const show = w.findAll('button').find((b) => b.text() === 'Show all players')
  ;(show?.element as HTMLElement).focus()
  await show?.trigger('click')
  await nextTick()
  expect([w.find('[data-test="pinned"]').exists(), w.findAll('[data-rank]').length]).toEqual([false, 3])
  document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await nextTick()
  await nextTick()
  expect([w.find('[data-test="pinned"]').exists(), document.activeElement?.textContent?.trim()]).toEqual([true, 'Show all players'])
})

it('results: "Show all players" is not offered when every player is in the top 10', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 10, entries: [...top(3), me(4, 900), ...top(6, 5)], you: { rank: 4, score: 900 } })
  const w = render()
  expect(w.findAll('button').some((b) => b.text() === 'Show all players')).toBe(false)
})

it('an ended quiz that no one played says so, with no podium, no list and no player range', async () => {
  await join(false)
  await receive({ type: 'quiz_ended', seq: 6, playerCount: 0, entries: [], you: null })
  const w = render()
  expect(w.get('[data-test="no-players"]').text()).toBe('No one played this quiz.')
  expect(w.find('[data-rank]').exists()).toBe(false)
  expect(w.find('ol').exists()).toBe(false)
  expect(w.findAll('button').some((b) => b.text() === 'Show all players')).toBe(false)
  expect(w.text()).not.toContain('Players 1–0 of 0')
})
