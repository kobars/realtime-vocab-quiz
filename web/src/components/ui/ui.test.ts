// AI-ASSISTED: shared UI components meet the focus-ring and touch-target rules and fill Progress against max.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { h } from 'vue'
import { badgeVariants } from './badge'
import { buttonVariants } from './button'
import { Input } from './input'
import { Progress } from './progress'

const classes = (value: string) => value.split(/\s+/)
const inputClass = () => mount(Input).get('input').classes().join(' ')

const buttonVariantNames = ['default', 'destructive', 'outline', 'secondary', 'ghost', 'link'] as const
const badgeVariantNames = ['default', 'secondary', 'destructive', 'outline'] as const
const focusables: [string, string][] = [
  ...buttonVariantNames.map((v): [string, string] => [`button ${v}`, buttonVariants({ variant: v })]),
  ...badgeVariantNames.map((v): [string, string] => [`badge ${v}`, badgeVariants({ variant: v })]),
  ['input', inputClass()],
]

describe('focus ring', () => {
  it.each(focusables)('%s draws a 2 px solid ring with a 2 px page-colored offset', (_, value) => {
    expect(classes(value)).toEqual(
      expect.arrayContaining([
        'focus-visible:ring-2',
        'focus-visible:ring-ring',
        'focus-visible:ring-offset-2',
        'focus-visible:ring-offset-background',
      ]),
    )
  })

  it.each(focusables)('%s never makes the ring translucent or thicker', (_, value) => {
    // A ring color with /alpha drops below 3:1 against the page.
    expect(value).not.toMatch(/(^|\s)(\S+:)?ring-[a-z-]+\/\d+/)
    expect(classes(value)).not.toContain('focus-visible:ring-3')
  })
})

describe('touch targets', () => {
  // Tailwind's spacing step is 4 px, so step 11 is 44 px.
  const height = (value: string) =>
    Math.max(0, ...[...value.matchAll(/(?:^|\s)(?:min-h|h|size)-(\d+)(?=\s|$)/g)].map((m) => Number(m[1])))

  it.each(['default', 'lg', 'icon', 'icon-lg'] as const)('button size %s is at least 44 px', (size) => {
    expect(height(buttonVariants({ size }))).toBeGreaterThanOrEqual(11)
  })

  it('input is at least 44 px tall', () => {
    expect(height(inputClass())).toBeGreaterThanOrEqual(11)
  })
})

describe('Progress', () => {
  const offset = (props: Record<string, unknown>) =>
    mount(() => h(Progress, props))
      .get('[data-slot="progress-indicator"]')
      .attributes('style')

  it.each([
    [{ modelValue: 3, max: 10 }, 'translateX(-70%)'],
    [{ modelValue: 40 }, 'translateX(-60%)'],
    [{ modelValue: 10, max: 10 }, 'translateX(-0%)'],
    [{ modelValue: null }, 'translateX(-100%)'],
    [{ modelValue: 15, max: 10 }, 'translateX(-0%)'],
  ])('fills %j as %s', (props, transform) => {
    expect(offset(props)).toContain(transform)
  })
})
