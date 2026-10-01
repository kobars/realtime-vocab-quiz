// AI-ASSISTED: a type-checked use of import.meta.env, so vue-tsc fails without the vite/client types.
import { describe, expect, it } from 'vitest'

describe('vite client types', () => {
  it('types import.meta.env', () => {
    const mode: string = import.meta.env.MODE
    expect(mode).toBe('test')
  })
})
