// AI-ASSISTED: tokens.css carries every light and dark token value of the UI spec's table, and reduced motion zeroes every motion token.
import { describe, expect, it } from 'vitest'
import spec from '../../../docs/spec/ui.md?raw'
import { dark as darkTokens, light as lightTokens } from './tokens'
import tokens from './tokens.css?raw'

// Rows such as "| `--motion-fast` / `--motion-base` | `120ms` / `200ms` | same | ..." pair names and values by
// position; the third cell holds the dark values, or "same".
const backticked = (cell: string) => [...cell.matchAll(/`([^`]+)`/g)].map((m) => m[1] ?? '')
const rows = spec
  .split('\n')
  .filter((row) => row.startsWith('| `--'))
  .map((row) => row.split('|').slice(1, 4).map(backticked))
const pairs = (column: 1 | 2) =>
  rows.flatMap((cells) => (cells[0] ?? []).map((name, i): [string, string | undefined] => [name, cells[column]?.[i]]))
const light = pairs(1)
const dark = pairs(2).filter((pair): pair is [string, string] => pair[1] !== undefined)
const reducedMotion = tokens.slice(tokens.indexOf('@media (prefers-reduced-motion: reduce)'))
const MOTION = ['--motion-fast', '--motion-base', '--motion-slow', '--motion-count', '--motion-pop', '--stagger']

describe('design tokens', () => {
  it('reads the spec table', () => {
    expect(light.length).toBeGreaterThanOrEqual(40)
    expect(dark.length).toBeGreaterThanOrEqual(25)
  })

  it.each(light)('%s is %s in the light theme', (name, value) => {
    expect(lightTokens[name]).toBe(value)
  })

  it.each(dark)('%s is %s in the dark theme', (name, value) => {
    expect(darkTokens[name]).toBe(value)
  })

  it('lists every token of tokens.css in the spec table, in both themes', () => {
    expect(light.map(([name]) => name).sort()).toEqual(Object.keys(lightTokens).sort())
    expect(dark.map(([name]) => name).sort()).toEqual(Object.keys(darkTokens).sort())
  })

  it('tells the browser each theme, so scrollbars and native controls follow it', () => {
    const block = (from: number) => tokens.slice(from, tokens.indexOf('}', from))
    expect(block(tokens.indexOf(':root {'))).toContain('color-scheme: light;')
    expect(block(tokens.indexOf('@media (prefers-color-scheme: dark)'))).toContain('color-scheme: dark;')
  })

  it.each(['--shadow-clay', '--shadow-clay-lift', '--shadow-press', '--shadow-press-hover', '--shadow-press-active'])(
    'the dark theme redefines %s with no sideways offset, so no ghost box sits beside a surface on the dark page',
    (name) => {
      const value = darkTokens[name] ?? ''
      // Each layer starts at depth 0; a layer of a color-mix() nests its commas in parentheses.
      const layers = value.replace(/\([^()]*(\([^()]*\)[^()]*)*\)/g, '()').split(',').map((layer) => layer.trim())
      expect(layers.length).toBeGreaterThan(0)
      for (const layer of layers) expect(layer).toMatch(/^0 \d+px /)
    },
  )

  it.each(MOTION)('reduced motion sets %s to 0ms', (name) => {
    expect(reducedMotion).toContain(`${name}: 0ms;`)
  })

  it('zeroes every duration token under reduced motion', () => {
    const durations = Object.keys(lightTokens).filter((name) => /^\d+ms$/.test(lightTokens[name] ?? ''))
    expect(durations.sort()).toEqual([...MOTION].sort())
  })
})
