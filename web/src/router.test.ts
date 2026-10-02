// AI-ASSISTED: route table, quiz guard and app-shell tests.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from './App.vue'
import { createAppRouter } from './router'
import { configureQuizStore, useQuizStore } from './stores/quiz'
import { strings } from './strings'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

async function at(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  return router
}

async function mountAt(path: string) {
  const wrapper = mount(App, { global: { plugins: [createPinia(), await at(path)] } })
  await flushPromises()
  return wrapper
}

describe('routes', () => {
  it.each([
    ['/', 'join', '/'],
    ['/quiz/VOCAB-42', 'join', '/?quiz=VOCAB-42'],
    ['/q/VOCAB-42', 'join', '/?quiz=VOCAB-42'],
    ['/nope', 'not-found', '/nope'],
    ['/quiz', 'not-found', '/quiz'],
    ['/quiz/VOCAB-42/extra', 'not-found', '/quiz/VOCAB-42/extra'],
  ])('%s shows %s at %s', async (path, name, fullPath) => {
    const route = (await at(path)).currentRoute.value
    expect([route.name, route.fullPath]).toEqual([name, fullPath])
  })
})

describe('quiz guard', () => {
  configureQuizStore({ createClient: () => ({ start: vi.fn(), next: vi.fn(), answer: vi.fn(), rejoin: vi.fn(), refresh: vi.fn(), getLeaderboard: vi.fn(), stop: vi.fn() }) })
  /** A join to `quizId`, then its `joined` reply. */
  const joinedTo = (quizId: string) => {
    useQuizStore().join(quizId, 'Ana')
    useQuizStore().$patch({ quiz: { quizId } as never })
  }
  /** A join to `quizId` after its end: the results with no binding. */
  const endedJoinTo = (quizId: string) => {
    useQuizStore().join(quizId, 'Ana')
    useQuizStore().$patch({ ended: true })
  }

  it('lets in the quiz the store is joined to, and the results of an ended quiz with no binding', async () => {
    joinedTo('VOCAB-42')
    expect((await at('/quiz/VOCAB-42')).currentRoute.value.name).toBe('quiz')
    setActivePinia(createPinia())
    endedJoinTo('VOCAB-42')
    expect((await at('/quiz/VOCAB-42')).currentRoute.value.name).toBe('quiz')
  })

  it('sends another quiz ID after a join to an ended quiz to the join screen, so it never shows those results', async () => {
    endedJoinTo('VOCAB-42')
    const router = await at('/quiz/VOCAB-42')
    await router.push('/quiz/OTHER-QUIZ')
    expect(router.currentRoute.value.fullPath).toBe('/?quiz=OTHER-QUIZ')
  })

  it('sends another quiz ID, also from inside the quiz screen, to the join screen with that ID filled in', async () => {
    joinedTo('VOCAB-42')
    const router = await at('/quiz/OTHER-1')
    expect(router.currentRoute.value.fullPath).toBe('/?quiz=OTHER-1')
    await router.push('/quiz/VOCAB-42')
    await router.push('/quiz/OTHER-1')
    expect(router.currentRoute.value.fullPath).toBe('/?quiz=OTHER-1')
  })
})

describe('app shell', () => {
  it('renders the header and the routed screen, sends a direct load of a quiz to the join screen, and links the 404 page back to the start', async () => {
    // The join screen looks the filled-in ID up.
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 404 })))
    const quiz = await mountAt('/quiz/VOCAB-42')
    expect(quiz.get('header').text()).toContain(strings.appName)
    expect(quiz.get('main h1').text()).toBe(strings.join.title)
    const missing = await mountAt('/missing')
    expect(missing.get('main h1').text()).toBe(strings.notFound.title)
    expect(missing.get('main a').attributes('href')).toBe('/')
  })
})
