// AI-ASSISTED: tests for the landing and join screen: validation, the share link, the preview and the join outcomes.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from '@/App.vue'
import type { ClientEvent } from '@/protocol/client'
import { createAppRouter } from '@/router'
import { configureQuizStore, type QuizClientPort } from '@/stores/quiz'
import { strings } from '@/strings'

let emit: (event: ClientEvent) => void
let start: ReturnType<typeof vi.fn>
let preview: { status: number; body: unknown }
const open = { title: 'Everyday words', questionCount: 10, status: 'open', players: 3 }

beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  start = vi.fn()
  preview = { status: 200, body: open }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(preview.body), { status: preview.status })))
  configureQuizStore({
    createClient: (onEvent) => {
      emit = onEvent
      return { start, next: vi.fn(), answer: vi.fn(), rejoin: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() } as unknown as QuizClientPort
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

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

describe('validation', () => {
  it('upper-cases the quiz ID as it is typed and limits the name to 32 characters', async () => {
    const { id, name } = await screen()
    await id.setValue('vocab-42')
    expect(id.element.value).toBe('VOCAB-42')
    expect(name.attributes('maxlength')).toBe('32')
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
    expect(fetch).toHaveBeenCalledWith('/api/quizzes/VOCAB-42')
  })

  it('shows "no quiz" under the field when the preview finds none, and does not join', async () => {
    preview = { status: 404, body: {} }
    const { id, name, describedBy, submit } = await screen()
    await id.setValue('NOPE-1')
    await name.setValue('Ana')
    await submit()
    expect(describedBy(id)).toContain(strings.join.notFound)
    expect(start).not.toHaveBeenCalled()
  })

  it('says when the quiz has ended and offers its results', async () => {
    preview = { status: 200, body: { ...open, status: 'ended' } }
    const { wrapper, button } = await screen('/q/VOCAB-42')
    expect(wrapper.text()).toContain(strings.join.ended)
    expect(button()).toBe(strings.join.submitEnded)
  })
})

describe('join', () => {
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
    emit({ v: 1, type: 'joined', atSeq: 0, quizId: 'VOCAB-42', userId: 'u1', displayName: 'Ana', questionCount: 10,
      timeLimitMs: 20_000, quizRemainingMs: 600_000, cursor: -1, cursorOpen: false, finished: false, score: 0 })
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

  it('opens the results when the quiz ended before the join', async () => {
    const { router } = await joining()
    emit({ v: 1, type: 'error', code: 'QUIZ_ENDED', message: '', requestType: 'join' })
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/quiz/VOCAB-42'))
  })
})
