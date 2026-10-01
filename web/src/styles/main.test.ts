// AI-ASSISTED: the Tailwind entry keeps the theme light only and puts default transitions on the motion tokens.
import { describe, expect, it } from 'vitest'
import main from './main.css?raw'

describe('Tailwind entry', () => {
  it('binds dark: to a .dark ancestor, not to prefers-color-scheme', () => {
    expect(main).toContain('@custom-variant dark (&:is(.dark *));')
    expect(main).not.toContain('prefers-color-scheme')
  })

  it.each([
    ['--default-transition-duration', 'var(--motion-base)'],
    ['--default-transition-timing-function', 'var(--ease-standard)'],
  ])('maps %s to %s, so reduced motion also stops transition-*', (name, value) => {
    const theme = main.slice(main.indexOf('@theme inline'))
    expect(theme).toContain(`${name}: ${value};`)
  })
})
