// AI-ASSISTED: recomputes the WCAG 2.x contrast of every text, outline and focus-ring pair from tokens.css, in both themes (UI spec §6.4).
import { describe, expect, it } from 'vitest'
import { dark, light, type Tokens } from './tokens'

/** The relative luminance of a `#RRGGBB` color (WCAG 2.2). */
function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05)
}

const TEXT = 4.5
const NON_TEXT = 3
// [foreground token, background token, minimum]: every pair a component draws.
const PAIRS: [string, string, number][] = [
  ...['--background', '--card', '--muted', '--highlight', '--warning-soft'].map((bg): [string, string, number] => ['--foreground', bg, TEXT]),
  ['--card-foreground', '--card', TEXT],
  ['--popover-foreground', '--popover', TEXT],
  ...['--background', '--card', '--muted'].map((bg): [string, string, number] => ['--muted-foreground', bg, TEXT]),
  ['--secondary-foreground', '--secondary', TEXT],
  ['--accent-foreground', '--accent', TEXT],
  ['--primary', '--background', TEXT],
  ['--primary', '--card', TEXT],
  ['--primary-foreground', '--primary', TEXT],
  ['--primary-foreground', '--primary-bright', TEXT],
  ['--primary-foreground', '--primary-hover', TEXT],
  ...['--mint', '--cyan', '--sun', '--input'].map((bg): [string, string, number] => ['--night', bg, TEXT]),
  ...['success', 'destructive', 'warning'].flatMap((state) =>
    ['--background', '--card', `--${state}-soft`].map((bg): [string, string, number] => [`--${state}`, bg, TEXT])),
  ['--destructive-foreground', '--destructive', TEXT],
  ['--input', '--background', NON_TEXT],
  ['--input', '--card', NON_TEXT],
  ['--ring', '--background', NON_TEXT],
  ['--ring', '--card', NON_TEXT],
  ['--primary', '--highlight', NON_TEXT],
]

const THEMES: [string, Tokens][] = [['light', light], ['dark', { ...light, ...dark }]]
const cases = THEMES.flatMap(([theme, tokens]) => PAIRS.map(([fg, bg, min]) => [theme, fg, bg, min, tokens] as const))

describe('contrast', () => {
  it.each(cases)('%s: %s on %s is at least %d:1', (_, fg, bg, min, tokens) => {
    const [a = '', b = ''] = [tokens[fg], tokens[bg]]
    expect(a).toMatch(/^#[0-9A-F]{6}$/)
    expect(b).toMatch(/^#[0-9A-F]{6}$/)
    expect(contrast(a, b)).toBeGreaterThanOrEqual(min)
  })

  it.each(THEMES)('%s: each stop of --gradient-text reads as normal text on the page', (_, tokens) => {
    const stops = (tokens['--gradient-text'] ?? '').match(/#[0-9A-F]{6}/g) ?? []
    expect(stops).toHaveLength(2)
    for (const stop of stops) expect(contrast(stop, tokens['--background'] ?? '')).toBeGreaterThanOrEqual(TEXT)
  })

  it('matches the published ratios', () => {
    expect(contrast('#FFFFFF', '#000000')).toBeCloseTo(21)
    expect(contrast('#181233', '#F9F6FF')).toBeCloseTo(16.75, 2)
    expect(contrast('#9774FF', '#F9F6FF')).toBeCloseTo(3.14, 2)
  })
})
