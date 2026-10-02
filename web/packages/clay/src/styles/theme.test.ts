// AI-ASSISTED: the Clay theme keeps dark: inert, serves the font from our origin, gives body the font and puts transitions and the clay utilities on the tokens.
import { describe, expect, it } from 'vitest'
import fonts from './fonts.css?raw'
import main from './theme.css?raw'

const base = main.slice(main.indexOf('@layer base'))
const theme = main.slice(main.indexOf('@theme inline'))

describe('Clay theme', () => {
  it('pulls in the tokens and the font, and scans the components for their classes', () => {
    expect(main).toContain("@import './tokens.css';")
    expect(main).toContain("@import './fonts.css';")
    expect(main).toContain("@source '../components';")
  })

  it('binds dark: to a .dark ancestor, not to prefers-color-scheme', () => {
    expect(main).toContain('@custom-variant dark (&:is(.dark *));')
    expect(main).not.toContain('prefers-color-scheme')
  })

  it('gives every focus-visible element a 2 px solid outline with a 2 px offset', () => {
    expect(base).toContain('* { @variant focus-visible { @apply outline-2 outline-solid outline-offset-2 outline-ring; } }')
  })

  it('focus-hug paints the focus outline over the control\'s own outline and 2 px past it, in --ring or in --destructive on an invalid field', () => {
    // All outline, so a border colour from hover, selection or a transition cannot show through the band.
    const rule = main.slice(main.indexOf('@utility focus-hug {'), main.indexOf('\n}', main.indexOf('@utility focus-hug {')))
    expect(rule).toContain('@variant focus-visible { outline-width: calc(var(--border-clay) + 2px); outline-offset: calc(-1 * var(--border-clay)); border-color: var(--ring); }')
    expect(rule).toContain("&[aria-invalid='true'] { @variant focus-visible { border-color: var(--destructive); outline-color: var(--destructive); } }")
  })

  it('sets the body in --font-sans at weight 500 and headings at weight 800', () => {
    expect(base).toMatch(/body \{ @apply [^}]*\bfont-sans\b[^}]*\bfont-medium\b/)
    expect(base).toMatch(/h1, h2, h3 \{ @apply [^}]*\bfont-extrabold\b/)
  })

  it('declares only the latin faces of the font, from the package, with font-display: swap', () => {
    expect(main).not.toContain('@font-face')
    const faces = fonts.match(/@font-face \{[^}]*\}/g) ?? []
    expect(faces).toHaveLength(2)
    for (const face of faces) {
      expect(face).toContain('font-display: swap;')
      // Relative to this package, so the app that imports the theme needs no font dependency of its own.
      expect(face).toMatch(/url\('\.\.\/\.\.\/node_modules\/@fontsource-variable\/nunito\/files\/nunito-latin(-ext)?-wght-normal\.woff2'\)/)
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

  it.each(['clay', 'clay-lift', 'press', 'press-hover', 'press-active', 'inset'])('the shadow-%s utility reads its token', (name) => {
    expect(main).toContain(`@utility shadow-${name} { box-shadow: var(--shadow-${name}); }`)
  })

  it('sets the podium delay after the animation shorthand, which would reset it', () => {
    const rise = main.match(/@utility animate-rise \{([^}]*)\}/)?.[1] ?? ''
    expect(rise.indexOf('animation-delay: calc(var(--stagger) * var(--rise-step, 0));')).toBeGreaterThan(rise.indexOf('animation: rise'))
    expect(main).toContain('@utility rise-delay-* { --rise-step: --value(integer); }')
  })

  it('keeps no grey shadow utility', () => {
    expect(main).not.toContain('shadow-card')
  })
})
