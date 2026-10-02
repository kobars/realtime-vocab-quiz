// AI-ASSISTED: component tests for the leaderboard rows, the live panel and "Show all players" paging (its loading status and the rows kept while paging), driven by server frames through the quiz store.
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
  for (const message of messages) emit({ v: 1, ...message } as ClientEvent)
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
const pageRanks = (w: VueWrapper) => w.findAll('section section li:not([class*="-leave-"])').map((li) => li.find('span').text())
const sent = () => port.getLeaderboard.mock.calls
const button = (w: VueWrapper, text: string) => w.findAll('button').find((b) => b.text() === text)
async function openAll() {
  await joinedStore()
  const w = render(LeaderboardPanel)
  await w.find('button').trigger('click')
  return w
}

beforeEach(() => {
  // performance.now() is the store's monotonic clock; moving the wall clock never changes it.
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date', 'performance'] })
  setActivePinia(createPinia())
  port = { start: vi.fn(), next: vi.fn(), answer: vi.fn(() => 's-1'), rejoin: vi.fn(), refresh: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() }
  configureQuizStore({ now: () => performance.now(), createClient: (onEvent) => ((emit = onEvent), port as unknown as QuizClientPort) })
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
  // It stays in view at the bottom of the window below up to 50 rows.
  expect(w.get('[data-test="pinned"]').classes()).toEqual(expect.arrayContaining(['sticky', 'bottom-0']))
  // My old row fades out (it keeps its leave class until the transition ends).
  expect(w.find('[aria-current="true"]:not(.lb-leave-active)').exists()).toBe(false)
  await receive(board(5, [me(1, 2_000), ...top(49, 2)]))
  expect(w.find('[data-test="pinned"]').exists()).toBe(false)
})

it('pages through get_leaderboard and reloads the open page at most once per second while scores move', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  await w.find('button').trigger('click')
  expect(sent()).toEqual([[0, 100]])
  await receive(page(7, 0, top(100)))
  expect(w.get('[data-test="page-range"]').text()).toBe('Players 1–100 of 300')
  expect(w.text()).not.toContain('As of update')
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
  expect(w.find('[data-user="p101"]').text()).toContain('9999')
  await vi.advanceTimersByTimeAsync(5_000)
  expect(sent()).toHaveLength(3)
})

it('a Loading players status shows until the first page arrives; paging keeps the shown rows until the next page arrives', async () => {
  const w = await openAll()
  const status = () => w.get('[data-test="page-status"]')
  expect([status().attributes('role'), status().text()]).toEqual(['status', 'Loading players…'])
  expect([w.find('[data-test="page-range"]').exists(), pageRanks(w)]).toEqual([false, []])
  await receive(page(7, 0, top(100)))
  expect([status().text(), pageRanks(w).length]).toEqual(['', 100])
  await button(w, 'Next')?.trigger('click')
  expect(status().text()).toBe('Loading players…')
  expect([pageRanks(w)[0], w.get('[data-test="page-range"]').text()]).toEqual(['#1', 'Players 1–100 of 300'])
  await receive(page(7, 100, top(100, 101)))
  expect([status().text(), pageRanks(w)[0], w.get('[data-test="page-range"]').text()]).toEqual(['', '#101', 'Players 101–200 of 300'])
})

it('after a close and a reopen on the first page, Next still keeps the shown rows until the next page arrives', async () => {
  const w = await openAll()
  await receive(page(7, 0, top(100)))
  await button(w, 'Close')?.trigger('click')
  await button(w, 'Show all players')?.trigger('click')
  expect(pageRanks(w).length).toBe(100)
  await button(w, 'Next')?.trigger('click')
  expect([pageRanks(w).length, pageRanks(w)[0], w.get('[data-test="page-range"]').text()]).toEqual([100, '#1', 'Players 1–100 of 300'])
})

it('a final page is never reloaded', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  await w.find('button').trigger('click')
  await receive(page(9, 0, top(100), true), board(10, top(50)))
  await vi.advanceTimersByTimeAsync(3_000)
  expect([sent(), w.find('[data-test="page-range"]').text()]).toEqual([[[0, 100]], 'Players 1–100 of 300 · Final standings'])
})

it('opening the panel moves the focus into it, so Escape closes it and focuses the button again', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  const toggle = w.find('button').element as HTMLElement
  toggle.focus()
  await w.find('button').trigger('click')
  await nextTick()
  expect(w.find('section section').element.contains(document.activeElement)).toBe(true)
  document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await nextTick()
  await nextTick()
  expect([w.find('button').text(), document.activeElement?.textContent?.trim()]).toEqual(['Show all players', 'Show all players'])
})

it('a pager button that disables itself hands the focus to the panel, so Escape still closes it', async () => {
  const w = await openAll()
  await receive(board(4, top(50), 150))
  const panel = w.find('section section').element
  for (const name of ['Next', 'Previous']) {
    const pager = button(w, name)
    ;(pager?.element as HTMLElement).focus()
    await pager?.trigger('click')
    await nextTick()
    expect([pager?.attributes('disabled'), document.activeElement]).toEqual(['', panel])
  }
  panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await nextTick()
  await nextTick()
  expect(document.activeElement?.textContent?.trim()).toBe('Show all players')
})

it('Previous or Next cancels a pending reload, and the final page it loads is not read again', async () => {
  const w = await openAll()
  await receive(page(7, 0, top(100)))
  await vi.advanceTimersByTimeAsync(100)
  await receive(board(8, top(50)))
  await vi.advanceTimersByTimeAsync(800)
  await button(w, 'Next')?.trigger('click')
  await receive(page(9, 100, top(100, 101), true))
  await vi.advanceTimersByTimeAsync(3_000)
  expect(sent()).toEqual([[0, 100], [100, 100]])
})

it('a page shows the ranks from its offset, even when an earlier page was short', async () => {
  const w = await openAll()
  await receive(page(7, 0, top(90)))
  await button(w, 'Next')?.trigger('click')
  await receive(page(7, 100, top(10, 101)))
  expect(pageRanks(w).slice(0, 2)).toEqual(['#101', '#102'])
  await button(w, 'Previous')?.trigger('click')
  await receive(page(7, 0, top(90)))
  expect([pageRanks(w).length, pageRanks(w).at(-1)]).toEqual([90, '#90'])
})

it('a store restart (a snapshot with a lower seq) makes the open page stale', async () => {
  const w = await openAll()
  await receive(board(5_000, top(50)), page(5_000, 0, top(100)))
  await receive({ type: 'snapshot', atSeq: 3, status: 'open', playerCount: 300, onlineCount: 290, entries: top(50), you: null })
  await receive(board(4, top(50)), board(5, top(50)))
  await vi.advanceTimersByTimeAsync(1_000)
  expect([sent(), pageRanks(w).length]).toEqual([[[0, 100], [0, 100]], 100])
})

it('a page request with no reply, or a refused one, is sent again at most once per second', async () => {
  const w = await openAll()
  await vi.advanceTimersByTimeAsync(999)
  expect(sent()).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(sent()).toHaveLength(2)
  await receive({ type: 'error', code: 'RATE_LIMITED', message: '', requestType: 'get_leaderboard' })
  await receive(board(4, top(50)), board(5, top(50)))
  await vi.advanceTimersByTimeAsync(1_000)
  expect(sent()).toEqual([[0, 100], [0, 100], [0, 100]])
  await receive(page(5, 0, top(100)))
  await vi.advanceTimersByTimeAsync(5_000)
  expect([sent().length, pageRanks(w).length]).toEqual([3, 100])
})

it('a page request keeps being sent once per second while every reply is lost and nothing else changes', async () => {
  await openAll()
  await vi.advanceTimersByTimeAsync(3_000)
  expect(sent()).toEqual([[0, 100], [0, 100], [0, 100], [0, 100]])
})

it('the reload throttle runs on the monotonic clock, so moving the wall clock back does not delay it', async () => {
  await openAll()
  await receive(page(3, 0, top(100)))
  vi.setSystemTime(Date.now() - 3_600_000)
  await receive(board(4, top(50)))
  await vi.advanceTimersByTimeAsync(1_000)
  expect(sent()).toEqual([[0, 100], [0, 100]])
})

it('a snapshot or a rebase frame swaps the rows in one step; an ordinary frame moves them', async () => {
  await joinedStore()
  const w = render(LeaderboardPanel)
  const flip = () => w.find('ol').attributes('data-flip')
  const swapped = [row(1, 140, 'p3'), me(2, 0), row(3, 0, 'p1')]
  await receive({ type: 'snapshot', atSeq: 4, status: 'open', playerCount: 3, onlineCount: 2, entries: swapped, you: { rank: 2, score: 0 } })
  expect(flip()).toBe('false')
  await receive(board(5, [row(1, 140), me(2, 0), row(3, 0)]))
  expect(flip()).toBe('true')
  await receive({ ...board(6, swapped), rebase: true })
  expect(flip()).toBe('false')
})

it('my row gets a 1 s tint when it moves up, and none when it moves down', async () => {
  const w = track(mount(LeaderboardRows, { ...options, props: { entries: [row(1, 140), me(2, 0)], myUserId: 'u1' } }))
  const mine = () => w.find('[aria-current="true"]').classes()
  // The tint is my row's only fill, so it never depends on the CSS order of two fills.
  expect(mine()).toContain('bg-highlight')
  expect(mine()).not.toContain('bg-card')
  expect(w.find('li:not([aria-current])').classes()).toContain('bg-card')
  await w.setProps({ entries: [me(1, 150), row(2, 140)] })
  expect(mine()).toContain('lb-rise')
  await vi.advanceTimersByTimeAsync(1_000)
  expect(mine()).not.toContain('lb-rise')
  await w.setProps({ entries: [row(1, 160), me(2, 150)] })
  expect(mine()).not.toContain('lb-rise')
})

it('the top 3 rank chips sit on the place fills under dark text; the rest are muted', () => {
  const chips = rows(top(4)).findAll('li').map((li) => li.get('span').classes())
  expect(chips.map((c) => c.find((name) => name.startsWith('bg-')))).toEqual(['bg-sun', 'bg-muted', 'bg-warning-soft', 'bg-muted'])
  expect(chips.map((c) => c.find((name) => name.startsWith('text-') && !name.startsWith('text-sm')))).toEqual(['text-night', 'text-foreground', 'text-foreground', 'text-muted-foreground'])
})

it('a long name truncates and keeps the full name in its title', () => {
  const name = 'A very long display name that does not fit'
  const span = rows([{ rank: 1, userId: 'p1', displayName: name, score: 10 }]).get('li').findAll('span')[1]
  expect([span?.classes(), span?.attributes('title')]).toEqual([expect.arrayContaining(['truncate', 'min-w-0']), name])
})

it('a leaving row fades where it was, not at the top of the list', async () => {
  const w = rows(top(3))
  const leaving = w.find('[data-user="p2"]').element as HTMLElement
  vi.spyOn(leaving, 'offsetTop', 'get').mockReturnValue(40)
  await w.setProps({ entries: [row(1, 1_490), row(2, 1_470, 'p3')] })
  expect([leaving.classList.contains('lb-leave-active'), leaving.style.top]).toEqual([true, '40px'])
})
