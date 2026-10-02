// AI-ASSISTED: recomputes the WCAG 2.x contrast of every text, outline and focus-ring pair from tokens.css, in both themes (UI spec §6.4).
import { describe, expect, it } from 'vitest'
import { contrast, CONTRAST_PAIRS, MIN_TEXT } from './contrast'
import { themes, type Tokens } from './tokens'

const THEMES = Object.entries(themes) as [string, Tokens][]
const cases = THEMES.flatMap(([theme, tokens]) => CONTRAST_PAIRS.map(({ fg, bg, min }) => [theme, fg, bg, min, tokens] as const))

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
    for (const stop of stops) expect(contrast(stop, tokens['--background'] ?? '')).toBeGreaterThanOrEqual(MIN_TEXT)
  })

  it('matches the published ratios', () => {
    expect(contrast('#FFFFFF', '#000000')).toBeCloseTo(21)
    expect(contrast('#181233', '#F9F6FF')).toBeCloseTo(16.75, 2)
    expect(contrast('#9774FF', '#F9F6FF')).toBeCloseTo(3.14, 2)
  })
})
