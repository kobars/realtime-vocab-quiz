// AI-ASSISTED: the dev server proxies /api and /ws to the API node.
import type { ProxyOptions } from 'vite'
import { afterEach, describe, expect, it, vi } from 'vitest'
import viteConfig from '../vite.config'

const proxy = () =>
  viteConfig({ mode: 'test', command: 'serve' }).server?.proxy as Record<string, ProxyOptions>

describe('dev proxy', () => {
  afterEach(() => vi.unstubAllEnvs())

  it.each([
    [undefined, 'http://127.0.0.1:8001'],
    ['  ', 'http://127.0.0.1:8001'],
    ['http://127.0.0.1:8002', 'http://127.0.0.1:8002'],
  ])('sends /api and /ws to the API with QUIZ_API_URL=%j', (value, target) => {
    if (value !== undefined) vi.stubEnv('QUIZ_API_URL', value)
    expect(proxy()['/api']).toEqual({ target, changeOrigin: true })
    expect(proxy()['/ws']).toEqual({ target, changeOrigin: true, ws: true })
  })
})
