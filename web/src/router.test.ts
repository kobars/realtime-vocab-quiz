// AI-ASSISTED: route table and app-shell tests.
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from './App.vue'
import { createAppRouter } from './router'
import { strings } from './strings'

async function at(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  return router
}

async function mountAt(path: string) {
  const wrapper = mount(App, { global: { plugins: [await at(path)] } })
  await flushPromises()
  return wrapper
}

describe('routes', () => {
  it.each([
    ['/', 'join', '/'],
    ['/quiz/VOCAB-42', 'quiz', '/quiz/VOCAB-42'],
    ['/q/VOCAB-42', 'join', '/?quiz=VOCAB-42'],
    ['/nope', 'not-found', '/nope'],
    ['/quiz', 'not-found', '/quiz'],
    ['/quiz/VOCAB-42/extra', 'not-found', '/quiz/VOCAB-42/extra'],
  ])('%s shows %s at %s', async (path, name, fullPath) => {
    const route = (await at(path)).currentRoute.value
    expect([route.name, route.fullPath]).toEqual([name, fullPath])
  })
})

describe('app shell', () => {
  it('renders the header and the routed screen, and links the 404 page back to the start', async () => {
    const quiz = await mountAt('/quiz/VOCAB-42')
    expect(quiz.get('header').text()).toContain(strings.appName)
    expect(quiz.get('main h1').text()).toBe(strings.quiz.title('VOCAB-42'))
    const missing = await mountAt('/missing')
    expect(missing.get('main h1').text()).toBe(strings.notFound.title)
    expect(missing.get('main a').attributes('href')).toBe('/')
  })
})
