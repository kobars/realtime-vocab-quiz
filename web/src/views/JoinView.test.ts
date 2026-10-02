// AI-ASSISTED: tests for the landing and join screen: the wordmark and decoration, validation, the share link, the preview, the join outcomes, the rejoin after a reload and the way back to a live quiz.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from '@/App.vue'
import type { ClientEvent } from '@/protocol/client'
import { createAppRouter } from '@/router'
import { configureQuizStore, type QuizClientPort } from '@/stores/quiz'
import { strings } from '@/strings'
import { stackedFocusClasses } from '@/components/ui/focus.testing'

let emit: (event: ClientEvent) => void
let start: ReturnType<typeof vi.fn>
/** Status 0 stands for a network failure. */
let preview: { status: number; body: unknown }
const open = { title: 'Everyday words', questionCount: 10, status: 'open', players: 3 }
const missing = { error: 'QUIZ_NOT_FOUND', message: 'Quiz not found.' }

beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  start = vi.fn()
  preview = { status: 200, body: open }
  vi.stubGlobal('fetch', vi.fn(async () => {
    if (preview.status === 0) throw new TypeError('offline')
    return new Response(JSON.stringify(preview.body), { status: preview.status })
  }))
  configureQuizStore({
    createClient: (onEvent) => {
      emit = onEvent
      return { start, next: vi.fn(), answer: vi.fn(), rejoin: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() } as unknown as QuizClientPort
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

/**
 * Types each key as one input event. A browser runs a microtask checkpoint after each listener of a user's input
 * event, so Vue flushes between them; happy-dom runs them back to back, which hides a listener that reads the caret
 * too late. The listeners added after this call are held and run one at a time with a flush after each.
 */
function typeLikeABrowser() {
  const held: (() => void)[] = []
  const add = HTMLInputElement.prototype.addEventListener
  vi.spyOn(HTMLInputElement.prototype, 'addEventListener').mockImplementation(function (this: HTMLInputElement, type, listener, options) {
    if (type !== 'input' || listener === null) return add.call(this, type, listener, options)
    const call = typeof listener === 'function' ? listener.bind(this) : listener.handleEvent.bind(listener)
    add.call(this, type, (event) => held.push(() => call(event)), options)
  })
  return async (el: HTMLInputElement, keys: string) => {
    el.focus()
    for (const key of keys) {
      const at = el.selectionStart ?? el.value.length
      el.value = el.value.slice(0, at) + key + el.value.slice(el.selectionEnd ?? at)
      el.setSelectionRange(at + 1, at + 1)
      el.dispatchEvent(new Event('input', { bubbles: true }))
      for (const run of held.splice(0)) {
        run()
        await flushPromises()
      }
    }
  }
}

async function screen(path = '/') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  const id = wrapper.get<HTMLInputElement>('#quiz-id')
  const name = wrapper.get<HTMLInputElement>('#display-name')
  const describedBy = (field: typeof id) =>
    (field.attributes('aria-describedby') ?? '').split(' ').map((ref) => document.getElementById(ref)?.textContent?.trim())
  const submit = async () => {
    await wrapper.get('form').trigger('submit')
    await flushPromises()
  }
  const button = () => wrapper.get('button[type=submit]').text()
  return { wrapper, router, id, name, describedBy, submit, button }
}

it('the header link is a 44 px touch target', async () => {
  const { wrapper } = await screen()
  expect(wrapper.get('header a').classes()).toContain('min-h-11')
})

it('the header link and the skip link use the page focus outline with no ring on top, the skip link hugging its own outline', async () => {
  const { wrapper } = await screen()
  const stacked = (selector: string) => stackedFocusClasses(wrapper.get(selector).classes())
  expect([stacked('header a'), stacked('[data-test="skip-link"]')]).toEqual([[], []])
  expect(wrapper.get('[data-test="skip-link"]').classes()).toContain('focus-hug')
})

it('keeps the app name as the wordmark text and hides its icon tile from assistive tech', async () => {
  const { wrapper } = await screen()
  const wordmark = wrapper.get('[data-test="wordmark"]')
  expect(wordmark.text()).toBe(strings.appName)
  expect(wordmark.get('svg').element.closest('[aria-hidden="true"]')).not.toBeNull()
})

it('draws the hero decoration as a pseudo-element, adding no node to the page', async () => {
  const { wrapper } = await screen()
  const hero = wrapper.get('[data-test="hero"]')
  expect(hero.classes()).toContain('hero-blobs')
  expect(hero.findAll('[aria-hidden="true"]')).toHaveLength(0)
})

it('hides the icons of the preview card and of a field message from assistive tech', async () => {
  const { wrapper, id } = await screen()
  await id.setValue('VOCAB-42')
  await id.trigger('blur')
  await flushPromises()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  for (const icon of wrapper.findAll('form svg')) expect(icon.element.closest('[aria-hidden="true"]')).not.toBeNull()
  expect(wrapper.findAll('form svg').length).toBeGreaterThanOrEqual(2)
})

it('the quiz preview inside the join card casts no shadow of its own, so shadows never stack', async () => {
  const { wrapper, id } = await screen()
  await id.setValue('VOCAB-42')
  await id.trigger('blur')
  await flushPromises()
  const card = wrapper.get('[data-slot="card"]')
  expect(card.text()).toContain(open.title)
  expect(card.findAll('*').filter((el) => el.classes().some((c) => c.startsWith('shadow-clay')))).toEqual([])
})

it('keeps both fields out of password managers and keeps their autocomplete hints', async () => {
  const { id, name } = await screen()
  for (const field of [id, name]) {
    expect(field.attributes()).toMatchObject({ 'data-1p-ignore': '', 'data-lpignore': 'true', 'data-bwignore': '', 'data-form-type': 'other' })
  }
  expect([id.attributes('autocomplete'), name.attributes('autocomplete')]).toEqual(['off', 'nickname'])
})

describe('validation', () => {
  it('upper-cases the quiz ID as it is typed and puts no native length limit on the name', async () => {
    const { id, name } = await screen()
    await id.setValue('vocab-42')
    expect(id.element.value).toBe('VOCAB-42')
    // A native maxlength counts UTF-16 units before the trim: it would cut valid names, such as 32 emoji.
    expect(name.attributes('maxlength')).toBeUndefined()
  })

  it('keeps the order and the caret of keys typed one by one, also mid-ID', async () => {
    const type = typeLikeABrowser()
    const { id, name } = await screen()
    await type(id.element, 'vocab-42')
    expect([id.element.value, id.element.selectionStart]).toEqual(['VOCAB-42', 8])
    id.element.setSelectionRange(3, 3)
    await type(id.element, 'x')
    expect([id.element.value, id.element.selectionStart]).toEqual(['VOCXAB-42', 4])
    await type(name.element, 'Kim')
    expect(name.element.value).toBe('Kim')
  })

  it('renders when sessionStorage cannot be read', async () => {
    vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const { name } = await screen()
    expect(name.element.value).toBe('')
  })

  it('checks the quiz ID on blur, links the message to the field and clears it once fixed', async () => {
    const { id, describedBy } = await screen()
    await id.setValue('ab')
    await id.trigger('blur')
    expect(id.attributes('aria-invalid')).toBe('true')
    expect(describedBy(id)).toEqual([strings.join.quizIdHint, strings.join.quizIdInvalid])
    await id.setValue('VOCAB-42')
    expect(id.attributes('aria-invalid')).toBeUndefined()
  })

  it('refuses an empty name, then sends the trimmed one', async () => {
    const { id, name, describedBy, submit } = await screen()
    await id.setValue('VOCAB-42')
    await name.setValue('   ')
    await submit()
    expect(describedBy(name)).toEqual([strings.join.nameRequired])
    expect(document.activeElement).toBe(name.element)
    expect(start).not.toHaveBeenCalled()
    await name.setValue('  Ana  ')
    await submit()
    expect(name.element.value).toBe('Ana')
    expect(start).toHaveBeenCalledWith('VOCAB-42', 'Ana')
  })

  it('fills the quiz ID from /q/:quizId and focuses the name', async () => {
    const { router, id, name } = await screen('/q/vocab-42')
    expect(router.currentRoute.value.name).toBe('join')
    expect(id.element.value).toBe('VOCAB-42')
    expect(document.activeElement).toBe(name.element)
  })
})

describe('preview', () => {
  it('shows the quiz from GET /quizzes/{id}', async () => {
    const { wrapper } = await screen('/q/VOCAB-42')
    expect(wrapper.text()).toContain(open.title)
    expect(wrapper.text()).toContain(strings.join.preview.players(3))
    expect(fetch).toHaveBeenCalledWith('/api/quizzes/VOCAB-42', expect.anything())
  })

  it('shows "no quiz" under the field when the preview finds none, and does not join', async () => {
    preview = { status: 404, body: missing }
    const { id, name, describedBy, submit } = await screen()
    await id.setValue('NOPE-1')
    await name.setValue('Ana')
    await submit()
    expect(describedBy(id)).toContain(strings.join.notFound)
    expect(start).not.toHaveBeenCalled()
  })

  it('keeps "no quiz" when the field is left again without an edit', async () => {
    preview = { status: 404, body: missing }
    const { id, describedBy } = await screen()
    await id.setValue('NOPE-1')
    await id.trigger('blur')
    await flushPromises()
    expect(describedBy(id)).toContain(strings.join.notFound)
    await id.trigger('blur')
    await flushPromises()
    expect(describedBy(id)).toContain(strings.join.notFound)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('announces "no quiz" in the polite preview region, which a lookup that ends after the focus left still reaches', async () => {
    preview = { status: 404, body: missing }
    const { wrapper, id, name } = await screen()
    await id.setValue('NOPE-1')
    await id.trigger('blur')
    ;(name.element as HTMLElement).focus()
    await flushPromises()
    const region = wrapper.get('[data-test="preview-status"]')
    expect([region.attributes('aria-live'), region.text()]).toEqual(['polite', strings.join.notFound])
    await id.setValue('NOPE-12')
    expect(region.text()).toBe('')
  })

  it.each([
    ['a server error', 503, {}],
    ['a network failure', 0, null],
    ['a body of the wrong shape', 200, { ...open, status: 'paused' }],
    ['a 404 from a missing route', 404, { detail: 'Not Found' }],
  ])('shows no preview after %s and still joins', async (_, status, body) => {
    preview = { status, body }
    const { wrapper, id, name, describedBy, submit } = await screen()
    await id.setValue('VOCAB-42')
    await name.setValue('Ana')
    await submit()
    expect(wrapper.text()).not.toContain(open.title)
    expect(describedBy(id)).not.toContain(strings.join.notFound)
    expect(start).toHaveBeenCalledWith('VOCAB-42', 'Ana')
  })

  it.each([
    ['a miss', 404, missing],
    ['a failed lookup', 503, {}],
  ])('asks again on submit after %s', async (_, status, body) => {
    preview = { status, body }
    const { id, name, submit } = await screen()
    await id.setValue('VOCAB-42')
    await id.trigger('blur')
    await flushPromises()
    preview = { status: 200, body: open }
    await name.setValue('Ana')
    await submit()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(start).toHaveBeenCalledWith('VOCAB-42', 'Ana')
  })

  it('says when the quiz has ended and offers its results', async () => {
    preview = { status: 200, body: { ...open, status: 'ended' } }
    const { wrapper, button } = await screen('/q/VOCAB-42')
    expect(wrapper.text()).toContain(strings.join.ended)
    expect(button()).toBe(strings.join.submitEnded)
  })
})

describe('join', () => {
  const joinedFrame: ClientEvent = { v: 1, type: 'joined', atSeq: 0, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10,
    timeLimitMs: 20_000, quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0 }

  async function joining() {
    sessionStorage.setItem('quiz.displayName', 'Ana')
    const view = await screen('/?quiz=VOCAB-42')
    expect(view.name.element.value).toBe('Ana')
    await view.submit()
    return view
  }

  it('shows the progress with readable fields, then opens the quiz on joined', async () => {
    const { router, id, button } = await joining()
    expect(button()).toBe(strings.join.joining)
    expect(id.attributes('readonly')).toBeDefined()
    emit(joinedFrame)
    // The quiz route loads its view lazily, so the navigation can take more than one flush.
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  it('shows QUIZ_NOT_FOUND under the quiz ID and lets the player retry', async () => {
    const { router, id, describedBy, button } = await joining()
    emit({ v: 1, type: 'error', code: 'QUIZ_NOT_FOUND', message: '', requestType: 'join' })
    await flushPromises()
    expect(describedBy(id)).toContain(strings.join.notFound)
    expect(document.activeElement).toBe(id.element)
    expect(button()).toBe(strings.join.submit)
    expect(router.currentRoute.value.name).toBe('join')
  })

  it.each([
    ['an error reply to the join', () => emit({ v: 1, type: 'error', code: 'INVALID_MESSAGE', message: '', requestType: 'join' })],
    ['a final close before joined', () => emit({ type: 'status', status: 'closed', code: 1000 })],
  ])('unlocks the form after %s and lets the player retry', async (_, fail) => {
    const { router, id, wrapper, button, submit } = await joining()
    fail()
    await flushPromises()
    expect(button()).toBe(strings.join.submit)
    expect(id.attributes('readonly')).toBeUndefined()
    expect(wrapper.get('[role=alert]').text()).toBe(strings.join.failed)
    expect(router.currentRoute.value.name).toBe('join')
    await submit()
    expect(start).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
  })

  it('keeps the progress and says the server is busy while the client sends a join that got UNAVAILABLE again', async () => {
    const { wrapper, button } = await joining()
    expect(wrapper.get('[data-test="join-status"]').text()).toBe('')
    emit({ v: 1, type: 'error', code: 'UNAVAILABLE', message: '', requestType: 'join' })
    await flushPromises()
    expect(button()).toBe(strings.join.joining)
    expect(wrapper.find('button[type=submit] svg').exists()).toBe(true)
    expect(wrapper.get('[data-test="join-status"]').attributes('role')).toBe('status')
    expect(wrapper.get('[data-test="join-status"]').text()).toBe(strings.connection.busy)
    expect(wrapper.text()).not.toContain(strings.join.failed)
  })

  it.each([
    ['UNSUPPORTED_VERSION', 'version', () => emit({ v: 1, type: 'error', code: 'UNSUPPORTED_VERSION', message: '', requestType: 'join' })],
    ['close 1008', 'policy', () => emit({ type: 'status', status: 'closed', code: 1008 })],
  ] as const)('a first join ended by %s shows the blocking card with Reload, not try again', async (_, blocked, fail) => {
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload })
    const { wrapper, button } = await joining()
    fail()
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain(strings.blocked[blocked].title)
    expect(wrapper.get('[role=alert] button').text()).toBe('Reload')
    expect(wrapper.text()).not.toContain(strings.join.failed)
    expect(button()).toBe(strings.join.submit)
    await wrapper.get('[role=alert] button').trigger('click')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it("10 connects without a joined show Still can't connect, whose Try again joins again and opens the quiz", async () => {
    const { wrapper, router } = await joining()
    emit({ type: 'status', status: 'failed', code: 1006 })
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain(strings.blocked.unreachable.title)
    expect(wrapper.text()).not.toContain(strings.join.failed)
    await wrapper.get('[role=alert] button').trigger('click')
    await flushPromises()
    expect(start).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    emit(joinedFrame)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  it('a reload of the quiz screen after a join in this tab joins again by itself and opens the quiz', async () => {
    const first = await joining()
    emit(joinedFrame)
    await vi.waitFor(() => expect(first.router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
    first.wrapper.unmount()
    // A reload: the page unloads, then a new store and router start; the tab's sessionStorage stays.
    window.dispatchEvent(new Event('pagehide'))
    setActivePinia(createPinia())
    const { router, id, button } = await screen('/quiz/VOCAB-42')
    expect(start).toHaveBeenLastCalledWith('VOCAB-42', 'Ana')
    expect(start).toHaveBeenCalledTimes(2)
    expect(button()).toBe(strings.join.joining)
    expect(id.element.value).toBe('VOCAB-42')
    emit(joinedFrame)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  it('a reload whose join ends before the lazily loaded join screen opens still opens the quiz', async () => {
    const first = await joining()
    emit(joinedFrame)
    await vi.waitFor(() => expect(first.router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
    first.wrapper.unmount()
    window.dispatchEvent(new Event('pagehide'))
    setActivePinia(createPinia())
    const router = createAppRouter(createMemoryHistory())
    await router.push('/quiz/VOCAB-42')
    expect(start).toHaveBeenCalledTimes(2)
    emit(joinedFrame)
    mount(App, { global: { plugins: [router] }, attachTo: document.body })
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  it('Try again on the blocking card joins the quiz that was sent, even after the quiz ID was edited', async () => {
    const { wrapper, router, id } = await joining()
    emit({ type: 'status', status: 'failed', code: 1006 })
    await flushPromises()
    await id.setValue('OTHER-1')
    await wrapper.get('[role=alert] button').trigger('click')
    await flushPromises()
    expect(start).toHaveBeenLastCalledWith('VOCAB-42', 'Ana')
    expect(id.element.value).toBe('VOCAB-42')
    emit(joinedFrame)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  it('after the wordmark leads away mid-quiz, Resume quiz goes back to the live quiz', async () => {
    const { wrapper, router } = await joining()
    emit(joinedFrame)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
    await wrapper.get('[data-test="wordmark"]').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
    await flushPromises()
    const resume = wrapper.get('[data-test="resume"]')
    expect(resume.text()).toBe(strings.join.resume('VOCAB-42'))
    await resume.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
    await flushPromises()
    expect(wrapper.get('main h1').text()).toBe(strings.quiz.title('VOCAB-42'))
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('keeps the progress while the client reconnects', async () => {
    const { button } = await joining()
    emit({ type: 'status', status: 'reconnecting', code: 1006 })
    await flushPromises()
    expect(button()).toBe(strings.join.joining)
  })

  it('reports a client that cannot start, for example with blocked storage', async () => {
    configureQuizStore({ createClient: () => { throw new DOMException('denied', 'SecurityError') } })
    const { wrapper, button } = await joining()
    expect(button()).toBe(strings.join.submit)
    expect(wrapper.get('[role=alert]').text()).toBe(strings.join.failed)
  })

  it('opens the results when the quiz ended before the join', async () => {
    const { router } = await joining()
    emit({ v: 1, type: 'error', code: 'QUIZ_ENDED', message: '', requestType: 'join' })
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })

  describe('while the lookup runs', () => {
    /** Each lookup waits until the test answers it, in any order. */
    function heldLookups() {
      const held: Array<(response: Response) => void> = []
      vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => held.push(resolve))))
      return (index: number, status: number, body: unknown) => {
        held[index]?.(new Response(JSON.stringify(body), { status }))
        return flushPromises()
      }
    }

    async function submitted() {
      const answer = heldLookups()
      sessionStorage.setItem('quiz.displayName', 'Ana')
      const view = await screen('/?quiz=VOCAB-42')
      await view.submit()
      expect(view.button()).toBe(strings.join.joining)
      return { ...view, answer }
    }

    it('ignores a link opened meanwhile and blocks the quiz that was sent when it is missing', async () => {
      const { router, id, describedBy, button, answer } = await submitted()
      await router.push('/?quiz=OTHER-1')
      await flushPromises()
      await answer(1, 200, open)
      await answer(0, 404, missing)
      expect(id.element.value).toBe('VOCAB-42')
      expect(describedBy(id)).toContain(strings.join.notFound)
      expect(button()).toBe(strings.join.submit)
      expect(start).not.toHaveBeenCalled()
    })

    it('ignores a link opened meanwhile and joins the quiz that was checked', async () => {
      const { router, answer } = await submitted()
      await router.push('/?quiz=OTHER-1')
      await flushPromises()
      await answer(0, 200, open)
      expect(start).toHaveBeenCalledWith('VOCAB-42', 'Ana')
    })

    it('does not join once the screen has closed', async () => {
      const { wrapper, answer } = await submitted()
      wrapper.unmount()
      await answer(0, 200, open)
      expect(start).not.toHaveBeenCalled()
    })
  })
})
