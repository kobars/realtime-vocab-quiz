// AI-ASSISTED: tokens.css carries every token value of the UI spec's direction A table.
import { describe, expect, it } from 'vitest'
import spec from '../../../docs/spec/ui.md?raw'
import tokens from './tokens.css?raw'

// Rows such as "| `--motion-fast` / `--motion-base` | `120ms` / `200ms` | ..." pair up by position.
const specTokens = spec
  .split('\n')
  .filter((row) => row.startsWith('| `--'))
  .flatMap((row) => {
    const [names = [], values = []] = row
      .split('|')
      .slice(1, 3)
      .map((cell) => [...cell.matchAll(/`([^`]+)`/g)].map((m) => m[1]))
    return names.map((name) => [name, values[names.indexOf(name)]])
  })
const [root = '', reducedMotion = ''] = tokens.split('@media (prefers-reduced-motion: reduce)')

describe('design tokens', () => {
  it('reads the spec table', () => {
    expect(specTokens.length).toBeGreaterThanOrEqual(20)
  })

  it.each(specTokens)('%s is %s', (name, value) => {
    expect(root).toContain(`${String(name)}: ${String(value)};`)
  })

  it.each(['fast', 'base', 'slow', 'count'])('reduced motion sets --motion-%s to 0ms', (name) => {
    expect(reducedMotion).toContain(`--motion-${name}: 0ms;`)
  })
})
