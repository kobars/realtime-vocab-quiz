// AI-ASSISTED: the Tailwind entry keeps dark: inert, serves the font from our origin, gives body the font and puts transitions and the clay utilities on the tokens.
import { describe, expect, it } from 'vitest'
import main from './main.css?raw'

const base = main.slice(main.indexOf('@layer base'))
const theme = main.slice(main.indexOf('@theme inline'))

describe('Tailwind entry', () => {
  it('binds dark: to a .dark ancestor, not to prefers-color-scheme', () => {
    expect(main).toContain('@custom-variant dark (&:is(.dark *));')
    expect(main).not.toContain('prefers-color-scheme')
  })

  it('gives every focus-visible element without ring classes a 2 px solid outline with a 2 px offset', () => {
    // Headings and panels focused from code have no ring classes; the controls with them set outline-none.
    expect(base).toContain(':focus-visible { @apply outline-2 outline-solid outline-offset-2 outline-ring; }')
  })

  it('sets the body in --font-sans at weight 500 and headings at weight 800', () => {
    expect(base).toMatch(/body \{ @apply [^}]*\bfont-sans\b[^}]*\bfont-medium\b/)
    expect(base).toMatch(/h1, h2, h3 \{ @apply [^}]*\bfont-extrabold\b/)
  })

  it('declares only the latin faces of the font, from the package, with font-display: swap', () => {
    const faces = main.match(/@font-face \{[^}]*\}/g) ?? []
    expect(faces).toHaveLength(2)
    for (const face of faces) {
      expect(face).toContain('font-display: swap;')
      expect(face).toMatch(/url\('@fontsource-variable\/nunito\/files\/nunito-latin(-ext)?-wght-normal\.woff2'\)/)
    }
  })

  it.each([
    ['--default-transition-duration', 'var(--motion-base)'],
    ['--default-transition-timing-function', 'var(--ease-standard)'],
  ])('maps %s to %s, so reduced motion also stops transition-*', (name, value) => {
    expect(theme).toContain(`${name}: ${value};`)
  })

  it.each([
    ['rounded-card', 'border-radius: var(--radius-card);'],
    ['border-clay', 'border-width: var(--border-clay);'],
    ['shadow-clay', 'box-shadow: var(--shadow-clay);'],
    ['shadow-clay-lift', 'box-shadow: var(--shadow-clay-lift);'],
    ['shadow-press', 'box-shadow: var(--shadow-press);'],
    ['shadow-press-hover', 'box-shadow: var(--shadow-press-hover);'],
    ['shadow-press-active', 'box-shadow: var(--shadow-press-active);'],
    ['bg-gradient-primary', 'background-image: var(--gradient-primary);'],
    ['ease-spring', 'transition-timing-function: var(--ease-spring);'],
  ])('the %s utility reads its token', (name, body) => {
    expect(main).toContain(`@utility ${name} { ${body} }`)
  })

  it('keeps no grey shadow utility', () => {
    expect(main).not.toContain('shadow-card')
  })
})
