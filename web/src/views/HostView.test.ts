// AI-ASSISTED: tests for the host screen: the bank list, every create outcome, the host panel (link, QR code, polled player count, copy), the end with its confirm step, and the refresh that keeps the controls.
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from '@/App.vue'
import { HOST_KEY, POLL_MS } from '@/components/host/hosting'
import { stackedFocusClasses } from '@/components/ui/focus.testing'
import { createAppRouter } from '@/router'
import { strings } from '@/strings'

interface Reply { status: number; body?: unknown; headers?: Record<string, string> }
/** Status 0 stands for a network failure; a null reply never settles. */
type Replies = Record<'banks' | 'create' | 'end' | 'preview', Reply | null>

const BANKS = [
  { id: 'VOCAB-42', title: 'Everyday English', questionCount: 10 },
  { id: 'BIZ-20', title: 'Business English', questionCount: 1 },
]
const CREATED = { quizId: 'VOCAB-42-7K3Q', sharePath: '/q/VOCAB-42-7K3Q', hostToken: 'secret', windowMs: 1_800_000, endsAtMs: Date.UTC(2026, 9, 2, 10, 30) }
const HOSTED = { quizId: CREATED.quizId, sharePath: CREATED.sharePath, hostToken: CREATED.hostToken, endsAtMs: CREATED.endsAtMs }
const preview = (players: number, status = 'open') => ({ status: 200, body: { title: 'Everyday English', questionCount: 10, status, players } })
let replies: Replies
// A panel left mounted would keep polling, and answer the visibility events of later tests.
enableAutoUnmount(afterEach)

function route(url: string, init?: RequestInit): keyof Replies {
  if (url === '/api/banks') return 'banks'
  if (url === '/api/quizzes') return 'create'
  return init?.method === 'POST' ? 'end' : 'preview'
}

beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  replies = { banks: { status: 200, body: BANKS }, create: { status: 201, body: CREATED }, end: { status: 200, body: { quizId: CREATED.quizId, status: 'ended', endSeq: 9 } }, preview: preview(3) }
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const reply = replies[route(url, init)]
    if (reply === null) return new Promise<never>(() => {})
    if (reply.status === 0) return Promise.reject(new TypeError('offline'))
    return Promise.resolve(new Response(JSON.stringify(reply.body ?? {}), { status: reply.status, headers: reply.headers }))
  }))
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

async function screen() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/host')
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  const bank = (id: string) => wrapper.get(`[data-bank="${id}"]`)
  const notice = () => wrapper.get('[data-test="host-notice"]').text()
  const calls = (kind: keyof Replies) => vi.mocked(fetch).mock.calls.filter(([url, init]) => route(url as string, init) === kind)
  const create = async () => {
    await bank('VOCAB-42').trigger('click')
    await flushPromises()
  }
  return { wrapper, router, bank, notice, calls, create }
}

describe('picking a question set', () => {
  it('says the sets are loading until the list arrives', async () => {
    replies.banks = null
    const { wrapper } = await screen()
    expect(wrapper.get('[role="status"]:not([data-test])').text()).toBe(strings.host.loading)
  })

  it('lists each set as a button with its title and question count, with one focus band each', async () => {
    const { wrapper, bank } = await screen()
    expect(wrapper.get('ul').attributes('aria-label')).toBe(strings.host.banksLabel)
    expect(bank('VOCAB-42').text()).toContain('Everyday English')
    expect(bank('BIZ-20').text()).toContain(strings.host.questions(1))
    expect(bank('VOCAB-42').classes()).toContain('focus-hug')
    expect(stackedFocusClasses(bank('VOCAB-42').classes())).toEqual([])
  })

  it('creates a quiz from the chosen set, keeps the host token in sessionStorage and moves the focus to the panel', async () => {
    const { wrapper, calls, create } = await screen()
    await create()
    expect(JSON.parse(String(calls('create')[0]?.[1]?.body))).toEqual({ bankQuizId: 'VOCAB-42' })
    expect(JSON.parse(sessionStorage.getItem(HOST_KEY) ?? 'null')).toEqual(HOSTED)
    expect(wrapper.get('[data-test="host-quiz-id"]').text()).toBe(CREATED.quizId)
    expect(document.activeElement?.textContent?.trim()).toBe(strings.host.ready)
  })

  it('shows "Creating…" on the chosen set and ignores clicks until the reply', async () => {
    replies.create = null
    const { bank, calls, create } = await screen()
    await create()
    expect(bank('VOCAB-42').text()).toContain(strings.host.creating)
    expect(bank('BIZ-20').attributes('aria-disabled')).toBe('true')
    await bank('BIZ-20').trigger('click')
    expect(calls('create')).toHaveLength(1)
  })

  it.each([
    [120, strings.host.minutes(2)],
    [30, strings.host.seconds(30)],
    [undefined, strings.host.minutes(1)],
  ])('after a 429 with Retry-After %s says when to try again and locks the sets until then', async (seconds, wait) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    replies.create = { status: 429, body: { error: 'RATE_LIMITED', message: 'Slow down.' }, headers: seconds === undefined ? {} : { 'Retry-After': String(seconds) } }
    const { bank, notice, calls, create } = await screen()
    await create()
    expect(notice()).toBe(strings.host.rateLimited(wait))
    expect(bank('VOCAB-42').attributes('aria-disabled')).toBe('true')
    await bank('VOCAB-42').trigger('click')
    expect(calls('create')).toHaveLength(1)
    vi.advanceTimersByTime((seconds ?? 60) * 1_000)
    await flushPromises()
    expect([notice(), bank('VOCAB-42').attributes('aria-disabled')]).toEqual(['', undefined])
  })

  it.each([
    ['the public slots are full', { status: 503, body: { error: 'HOSTING_FULL', message: 'Full.' } }, strings.host.full],
    ['the request fails', { status: 0 }, strings.host.error],
    ['the reply is a 500', { status: 500 }, strings.host.error],
    ['the reply has the wrong shape', { status: 201, body: { quizId: 'X' } }, strings.host.error],
  ])('says so when %s, and the sets stay open', async (_, reply, message) => {
    replies.create = reply
    const { bank, notice, create } = await screen()
    await create()
    expect(notice()).toBe(message)
    expect(bank('VOCAB-42').attributes('aria-disabled')).toBeUndefined()
  })

  it('reloads the list after a 422 for a set that is no longer offered', async () => {
    replies.create = { status: 422, body: { error: 'INVALID_MESSAGE', message: 'Unknown bank.' } }
    const { notice, calls, create } = await screen()
    await create()
    expect(notice()).toBe(strings.host.invalid)
    expect(calls('banks')).toHaveLength(2)
  })

  it.each([
    ['the bank list', 'banks'],
    ['the create', 'create'],
  ] as const)('shows that hosting is off when %s answers 404, with a way back', async (_, kind) => {
    replies[kind] = { status: 404, body: { error: 'NOT_FOUND', message: 'Not found.' } }
    const { wrapper, create } = await screen()
    if (kind === 'create') await create()
    const card = wrapper.get('[data-test="host-unavailable"]')
    expect(card.text()).toContain(strings.host.off)
    expect(card.get('a').attributes('href')).toBe('/')
  })

  it('shows that hosting is off when the list is empty', async () => {
    replies.banks = { status: 200, body: [] }
    const { wrapper } = await screen()
    expect(wrapper.get('[data-test="host-unavailable"]').text()).toContain(strings.host.off)
  })

  it('renders and creates with storage blocked, where even reading sessionStorage throws', async () => {
    vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const { wrapper, create } = await screen()
    await create()
    expect(wrapper.get('[data-test="host-quiz-id"]').text()).toBe(CREATED.quizId)
  })

  it('keeps a quiz created after the visitor left the page, so /host shows it again', async () => {
    const { wrapper, router, create } = await screen()
    let settle: (response: Response) => void = () => {}
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => (settle = resolve)))
    await create()
    await router.push('/')
    await flushPromises()
    settle(new Response(JSON.stringify(CREATED), { status: 201 }))
    await flushPromises()
    expect(JSON.parse(sessionStorage.getItem(HOST_KEY) ?? 'null')).toEqual(HOSTED)
    await router.push('/host')
    await flushPromises()
    expect(wrapper.get('[data-test="host-quiz-id"]').text()).toBe(CREATED.quizId)
  })

  it('offers "Try again" when the list cannot be loaded', async () => {
    replies.banks = { status: 0 }
    const { wrapper } = await screen()
    expect(wrapper.get('[data-test="host-unavailable"]').text()).toContain(strings.host.error)
    replies.banks = { status: 200, body: BANKS }
    await wrapper.get('[data-test="host-unavailable"] button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-bank]')).toHaveLength(2)
  })
})

describe('the host panel', () => {
  async function hosting() {
    const view = await screen()
    await view.create()
    return view
  }

  it('shows the full player link, its QR code and the live player count', async () => {
    const { wrapper } = await hosting()
    const url = `${window.location.origin}${CREATED.sharePath}`
    expect(wrapper.get<HTMLInputElement>('#share-link').element.value).toBe(url)
    expect(wrapper.get('svg[role="img"]').attributes('aria-label')).toBe(strings.host.qrLabel(url))
    expect(wrapper.get('svg[role="img"] path').attributes('d')).toMatch(/^M\d+ \d+h1v1h-1z/)
    const players = wrapper.get('[data-test="players"]')
    expect([players.attributes('aria-live'), players.text()]).toEqual(['polite', strings.host.players(3)])
    expect(wrapper.get('[data-test="join-as-player"]').attributes()).toMatchObject({ href: url, target: '_blank' })
  })

  it('reads the player count every few seconds while the page is visible, and not while it is hidden', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { wrapper, calls } = await hosting()
    replies.preview = preview(1)
    vi.advanceTimersByTime(POLL_MS)
    await flushPromises()
    expect(wrapper.get('[data-test="players"]').text()).toBe(strings.host.players(1))
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    const before = calls('preview').length
    vi.advanceTimersByTime(POLL_MS * 3)
    expect(calls('preview')).toHaveLength(before)
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(calls('preview')).toHaveLength(before + 1) // at once on coming back
    vi.advanceTimersByTime(POLL_MS)
    expect(calls('preview')).toHaveLength(before + 2)
  })

  it.each([
    ['its window closes', preview(4, 'ended')],
    ['it no longer exists', { status: 404, body: { error: 'QUIZ_NOT_FOUND', message: 'No quiz.' } }],
  ])('shows the ended card when the poll finds that %s', async (_, reply) => {
    replies.preview = reply
    const { wrapper } = await hosting()
    expect(wrapper.get('[data-test="host-ended"] h2').text()).toBe(strings.host.ended(CREATED.quizId))
    expect(sessionStorage.getItem(HOST_KEY)).toBeNull()
  })

  it.each([
    ['copied', () => Promise.resolve(), strings.host.copied],
    ['refused', () => Promise.reject(new Error('denied')), strings.host.copyFailed],
  ])('says when the link was %s', async (_, writeText, message) => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(writeText) } })
    const { wrapper } = await hosting()
    await wrapper.get('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${window.location.origin}${CREATED.sharePath}`)
    expect(wrapper.get('[data-test="copy-status"]').text()).toBe(message)
  })

  it('keeps the host controls after a refresh of the tab, without listing the sets again', async () => {
    sessionStorage.setItem(HOST_KEY, JSON.stringify(HOSTED))
    const { wrapper, calls } = await screen()
    expect(wrapper.get('[data-test="host-quiz-id"]').text()).toBe(CREATED.quizId)
    expect(calls('banks')).toHaveLength(0)
  })
})

describe('ending the quiz', () => {
  async function confirming() {
    const view = await screen()
    await view.create()
    await view.wrapper.get('[data-test="end"]').trigger('click')
    return view
  }

  it('asks first, with the focus on "Keep it open", which goes back to "End quiz"', async () => {
    const { wrapper, calls } = await confirming()
    expect(wrapper.get('[data-test="confirm-end"]').text()).toContain(strings.host.confirmEnd)
    expect(document.activeElement?.getAttribute('data-test')).toBe('keep-open')
    await wrapper.get('[data-test="keep-open"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="confirm-end"]').exists()).toBe(false)
    expect(document.activeElement?.getAttribute('data-test')).toBe('end')
    expect(calls('end')).toHaveLength(0)
  })

  it.each([
    ['ended', { status: 200 }],
    ['already ended', { status: 409, body: { error: 'QUIZ_ENDED', message: 'Ended.' } }],
    ['gone', { status: 404, body: { error: 'QUIZ_NOT_FOUND', message: 'No quiz.' } }],
  ])('sends the host token and shows the ended card when the quiz is %s', async (_, reply) => {
    replies.end = reply
    const { wrapper, calls } = await confirming()
    await wrapper.get('[data-test="confirm"]').trigger('click')
    await flushPromises()
    expect(calls('end')[0]?.[0]).toBe(`/api/quizzes/${CREATED.quizId}/end`)
    expect(calls('end')[0]?.[1]?.headers).toEqual({ 'X-Host-Token': CREATED.hostToken })
    expect(document.activeElement?.textContent?.trim()).toBe(strings.host.ended(CREATED.quizId))
    expect(wrapper.get('[data-test="host-ended"] a').attributes('href')).toBe(CREATED.sharePath)
    expect(sessionStorage.getItem(HOST_KEY)).toBeNull()
  })

  it('shows "Ending…" while the request runs, with "Keep it open" disabled', async () => {
    replies.end = null
    const { wrapper } = await confirming()
    await wrapper.get('[data-test="confirm"]').trigger('click')
    expect(wrapper.get('[data-test="confirm"]').attributes('aria-busy')).toBe('true')
    expect(wrapper.get('[data-test="confirm"]').text()).toBe(strings.host.ending)
    expect(wrapper.get('[data-test="keep-open"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="keep-open"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-end"]').exists()).toBe(true)
  })

  it.each([
    ['a wrong token', { status: 403, body: { error: 'FORBIDDEN', message: 'No.' } }, strings.host.forbidden],
    ['a network failure', { status: 0 }, strings.host.endFailed],
  ])('keeps the panel and says so after %s', async (_, reply, message) => {
    replies.end = reply
    const { wrapper } = await confirming()
    await wrapper.get('[data-test="confirm"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe(message)
    expect(wrapper.find('[data-test="host-panel"]').exists()).toBe(true)
  })

  it('"Host another quiz" lists the sets again', async () => {
    const { wrapper } = await confirming()
    await wrapper.get('[data-test="confirm"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="host-ended"] button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-bank]')).toHaveLength(2)
  })
})
