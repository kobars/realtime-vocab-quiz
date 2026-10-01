// AI-ASSISTED: the Tailwind entry keeps the theme light only and puts default transitions on the motion tokens.
import { describe, expect, it } from 'vitest'
import main from './main.css?raw'

describe('Tailwind entry', () => {
  it('binds dark: to a .dark ancestor, not to prefers-color-scheme', () => {
    expect(main).toContain('@custom-variant dark (&:is(.dark *));')
    expect(main).not.toContain('prefers-color-scheme')
  })

  it('gives every focus-visible element without ring classes a 2 px solid outline with a 2 px offset', () => {
    // Headings and panels focused from code have no ring classes; the controls with them set outline-none.
    const base = main.slice(main.indexOf('@layer base'))
    expect(base).toContain(':focus-visible { @apply outline-2 outline-solid outline-offset-2 outline-ring; }')
  })

  it.each([
    ['--default-transition-duration', 'var(--motion-base)'],
    ['--default-transition-timing-function', 'var(--ease-standard)'],
  ])('maps %s to %s, so reduced motion also stops transition-*', (name, value) => {
    const theme = main.slice(main.indexOf('@theme inline'))
    expect(theme).toContain(`${name}: ${value};`)
  })
})
