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
    ['bg-gradient-primary', 'background-image: var(--gradient-primary);'],
    ['ease-spring', 'transition-timing-function: var(--ease-spring);'],
  ])('the %s utility reads its token', (name, body) => {
    expect(main).toContain(`@utility ${name} { ${body} }`)
  })

  it.each(['clay', 'clay-lift', 'press', 'press-hover', 'press-active', 'inset'])(
    'shadow-%s fills the shadow slot and keeps the ring slots, so a focus ring survives hover and press',
    (name) => {
      const rule = main.match(new RegExp(`@utility shadow-${name} \\{([^}]*)\\}`))?.[1] ?? ''
      expect(rule).toContain(`--tw-shadow: var(--shadow-${name});`)
      expect(rule).toMatch(/box-shadow: [^;]*var\(--tw-ring-offset-shadow[^;]*var\(--tw-ring-shadow[^;]*var\(--tw-shadow\);/)
    },
  )

  it('sets the podium delay after the animation shorthand, which would reset it', () => {
    const rise = main.match(/@utility animate-rise \{([^}]*)\}/)?.[1] ?? ''
    expect(rise.indexOf('animation-delay: calc(var(--stagger) * var(--rise-step, 0));')).toBeGreaterThan(rise.indexOf('animation: rise'))
    expect(main).toContain('@utility rise-delay-* { --rise-step: --value(integer); }')
  })

  it('keeps no grey shadow utility', () => {
    expect(main).not.toContain('shadow-card')
  })
})
