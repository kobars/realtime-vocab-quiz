// AI-ASSISTED: app code takes every colour, radius, shadow and duration from the Clay design system, never a raw value.
import { describe, expect, it } from 'vitest'
import entry from './main.css?raw'

// The app's own source, without its tests and the generated protocol types.
const sources = Object.entries(
  import.meta.glob<string>(['./**/*.{ts,vue}', '!./**/*.test.ts', '!./**/*.generated.ts'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }),
)
const PALETTE = 'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose'
const COLOURED = 'bg|text|border|ring|outline|fill|stroke|from|via|to|shadow|decoration'
// A class starts after a space, a quote or a variant's colon, never inside a longer name such as rise-delay-2.
const CLASS_START = String.raw`(?<![\w-])`
const RAW: [string, RegExp][] = [
  ['a hex colour', /#[0-9a-f]{3,8}\b/i],
  ['a colour function', /\b(rgba?|hsla?|oklch|oklab|lab|lch)\(/],
  ['an arbitrary colour, radius or shadow class', /\b(bg|text|border|ring|outline|fill|stroke|from|via|to|shadow|rounded|decoration|caret)-\[/],
  ['a Tailwind palette colour', new RegExp(`${CLASS_START}(${COLOURED})-((${PALETTE})-\\d{2,3}|white|black)\\b`)],
  ['a stock shadow or radius', new RegExp(`${CLASS_START}(shadow-(2xs|xs|sm|md|lg|xl|2xl)|rounded(-(t|r|b|l|s|e|tl|tr|br|bl|ss|se|es|ee))?-(xs|2xl|3xl|4xl))\\b`)],
  ['a stock duration or delay', new RegExp(`${CLASS_START}(duration|delay)-\\d+\\b`)],
  ['a pixel or millisecond value', /\b\d+(px|ms)\b/],
]

describe('app code and the design system', () => {
  it('finds the app source', () => {
    expect(sources.length).toBeGreaterThan(20)
  })

  const isRaw = (cls: string) => RAW.some(([, pattern]) => pattern.test(`class="${cls}"`))
  it.each(['bg-white', 'hover:text-black', 'border-red-500', 'rounded-t-3xl', 'rounded-xs', 'shadow-md', 'duration-500', 'delay-150'])(
    'refuses the raw class %s',
    (cls) => {
      expect(isRaw(cls)).toBe(true)
    },
  )
  it.each(['bg-card', 'text-night/60', 'rounded-t-xl', 'rounded-card', 'shadow-press', 'duration-fast', 'rise-delay-2'])(
    'accepts the token class %s',
    (cls) => {
      expect(isRaw(cls)).toBe(false)
    },
  )

  it.each(sources.flatMap(([file, source]) => RAW.map(([what, pattern]) => [file, what, pattern, source] as const)))(
    '%s has no %s',
    (_, __, pattern, source) => {
      expect(source).not.toMatch(pattern)
    },
  )

  it('takes Tailwind and the Clay theme from the package, and defines no theme of its own', () => {
    // Tailwind scans only the app's source; the theme adds the package's components, not its gallery or docs.
    expect(entry).toMatch(/@import 'tailwindcss' source\('\.'\);\s*@import '@quiz\/clay\/theme\.css';/)
    expect(entry).not.toMatch(/@theme|@utility|@font-face|--[\w-]+\s*:/)
  })
})
