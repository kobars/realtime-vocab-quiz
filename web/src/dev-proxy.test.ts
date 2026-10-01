// AI-ASSISTED: the dev server proxies /api (prefix stripped) and /ws to the API node.
import type { ProxyOptions } from 'vite'
import { afterEach, describe, expect, it, vi } from 'vitest'
import viteConfig from '../vite.config'

const proxy = () =>
  viteConfig({ mode: 'test', command: 'serve' }).server?.proxy as Record<string, ProxyOptions>

describe('dev proxy', () => {
  afterEach(() => vi.unstubAllEnvs())

  // Every case sets QUIZ_API_URL: a value in process.env wins over the shell and any .env file.
  it.each([
    ['', 'http://127.0.0.1:8001'],
    ['  ', 'http://127.0.0.1:8001'],
    ['http://127.0.0.1:8002', 'http://127.0.0.1:8002'],
  ])('sends /api and /ws to the API with QUIZ_API_URL=%j', (value, target) => {
    vi.stubEnv('QUIZ_API_URL', value)
    expect(proxy()['/api']).toMatchObject({ target, changeOrigin: true })
    expect(proxy()['/ws']).toEqual({ target, changeOrigin: true, ws: true })
  })

  it.each([
    ['/api/sessions', '/sessions'],
    ['/api/tickets', '/tickets'],
    ['/api/sessions?x=/api', '/sessions?x=/api'],
  ])('rewrites %s to the API path %s', (path, apiPath) => {
    expect(proxy()['/api']?.rewrite?.(path)).toBe(apiPath)
  })
})
