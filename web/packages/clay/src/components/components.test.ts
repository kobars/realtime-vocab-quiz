// AI-ASSISTED: the Clay components render their variants, pass their accessibility attributes, bind Input with v-model, meet the focus-ring and touch-target rules, read only the clay tokens, keep press and lift behind motion-safe and fill Progress against max.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { h } from 'vue'
import { stackedFocusClasses } from '../testing'
import { cn } from '../utils'
import { Badge, badgeVariants } from './badge'
import { Button, buttonVariants } from './button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './card'
import { Input } from './input'
import { Progress } from './progress'
import { Toaster } from './sonner'

const classes = (value: string) => value.split(/\s+/)
const inputClass = () => mount(Input).get('input').classes().join(' ')

const buttonVariantNames = ['default', 'destructive', 'mint', 'outline', 'secondary', 'ghost', 'link'] as const
const buttonSizes = ['default', 'sm', 'lg', 'icon', 'icon-lg'] as const
const badgeVariantNames = ['default', 'secondary', 'mint', 'cyan', 'sun', 'success', 'destructive', 'warning', 'outline'] as const
const filled = ['default', 'destructive', 'mint'] as const
const outlined: [string, string][] = [
  ...(['outline', 'secondary', 'ghost', 'link'] as const).map((v): [string, string] => [`button ${v}`, buttonVariants({ variant: v })]),
  ['input', inputClass()],
]
const styled: [string, string][] = [
  ...buttonVariantNames.map((v): [string, string] => [`button ${v}`, buttonVariants({ variant: v })]),
  ...badgeVariantNames.map((v): [string, string] => [`badge ${v}`, badgeVariants({ variant: v })]),
  ['input', inputClass()],
]

// The page's :focus-visible outline is the one indicator (main.test.ts checks it); a second one stacks a ring on it.
describe('focus indicator', () => {
  it.each(styled)('%s adds no ring and does not hide the outline', (_, value) => {
    expect(stackedFocusClasses(classes(value))).toEqual([])
  })

  it.each(outlined)('%s draws its own outline, so the focus outline hugs it as one band', (_, value) => {
    expect(classes(value)).toContain('focus-hug')
  })

  it.each(filled)('button %s keeps the 2 px gap, which separates the outline from its fill', (variant) => {
    expect(classes(buttonVariants({ variant }))).not.toContain('focus-hug')
  })
})

describe('touch targets', () => {
  // Tailwind's spacing step is 4 px, so step 11 is 44 px.
  const height = (value: string) =>
    Math.max(0, ...[...value.matchAll(/(?:^|\s)(?:min-h|h|size)-(\d+)(?=\s|$)/g)].map((m) => Number(m[1])))

  it.each(buttonSizes)('button size %s is at least 44 px', (size) => {
    expect(height(buttonVariants({ size }))).toBeGreaterThanOrEqual(11)
  })

  it('input is at least 44 px tall', () => {
    expect(height(inputClass())).toBeGreaterThanOrEqual(11)
  })

  it('input text stays 16 px at every width', () => {
    expect(classes(inputClass())).toContain('text-base')
    expect(inputClass()).not.toMatch(/\b(sm|md|lg|xl|2xl):text-/)
  })
})

describe('clay look', () => {
  // Every primitive's source, to check what no class may carry.
  const sources = import.meta.glob<string>(['./*/*.vue', './*/index.ts'], { query: '?raw', import: 'default', eager: true })
  const cardClass = (interactive = false) => mount(Card, { props: { interactive } }).get('[data-slot="card"]').classes().join(' ')
  const moving = [
    ...(['default', 'destructive', 'mint', 'outline'] as const).map((v): [string, string] => [`button ${v}`, buttonVariants({ variant: v })]),
    ['interactive card', cardClass(true)],
  ]

  it.each(Object.entries(sources))('%s has no dark: class; the dark theme comes from the tokens', (_, source) => {
    expect(source).not.toMatch(/\bdark:/)
  })

  it.each(Object.entries(sources))('%s names no raw color, pixel or millisecond value', (_, source) => {
    expect(source).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|\d+px\b|\d+ms\b|-\[[^\]]*\d(px|ms|rem)\]/i)
  })

  it.each(moving)('%s moves only behind motion-safe:', (_, value) => {
    const transforms = classes(value).filter((c) => /translate-|scale-/.test(c))
    expect(transforms.length).toBeGreaterThan(0)
    for (const c of transforms) expect(c).toMatch(/^motion-safe:/)
  })

  it.each(moving)('%s eases its move: Tailwind translate-* sets the translate property, so the transition lists it', (_, value) => {
    expect(classes(value).filter((c) => c.startsWith('transition-'))).toEqual([expect.stringMatching(/^transition-\[[^\]]*\btranslate\b/)])
  })

  it.each([
    ['default', ['bg-primary', 'bg-gradient-primary', 'text-primary-foreground', 'shadow-press', 'border-clay']],
    ['mint', ['bg-mint', 'text-night', 'shadow-press']],
    ['outline', ['border-input', 'bg-card', 'text-primary', 'hover:bg-primary-hover', 'hover:text-primary-foreground']],
    ['destructive', ['bg-destructive', 'text-destructive-foreground']],
    ['secondary', ['bg-secondary', 'text-secondary-foreground']],
  ] as const)('button %s reads its tokens', (variant, expected) => {
    expect(classes(buttonVariants({ variant }))).toEqual(expect.arrayContaining([...expected]))
  })

  it.each([
    ['mint', 'bg-mint'], ['cyan', 'bg-cyan'], ['sun', 'bg-sun'],
  ] as const)('badge %s puts night text on its role fill', (variant, fill) => {
    expect(classes(badgeVariants({ variant }))).toEqual(expect.arrayContaining([fill, 'text-night', 'border-2', 'rounded-full']))
  })

  it.each(['success', 'destructive', 'warning'] as const)('badge %s puts state text on its soft fill', (variant) => {
    expect(classes(badgeVariants({ variant }))).toEqual(expect.arrayContaining([`bg-${variant}-soft`, `text-${variant}`]))
  })

  it('card is a clay card, and lifts only when interactive', () => {
    expect(classes(cardClass())).toEqual(expect.arrayContaining(['rounded-card', 'border-clay', 'border-border', 'shadow-clay', 'bg-card']))
    expect(cardClass()).not.toContain('hover:')
    expect(classes(cardClass(true))).toContain('hover:shadow-clay-lift')
  })

  it('badge renders a leading icon before its text', () => {
    const badge = mount(Badge, { slots: { icon: '<svg data-test="icon" />', default: 'Live' } })
    expect(badge.html()).toMatch(/data-test="icon".*Live/s)
  })

  it.each([
    ['border-clay border-input', 'border-clay border-input'],
    ['shadow-clay shadow-press', 'shadow-press'],
    ['text-title text-night', 'text-title text-night'],
    ['bg-gradient-primary bg-card', 'bg-gradient-primary bg-card'],
    ['rounded-card rounded-lg', 'rounded-lg'],
  ])('cn(%j) keeps %j', (input, kept) => {
    expect(cn(input)).toBe(kept)
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

describe('variants render', () => {
  it.each(buttonVariantNames.flatMap((variant) => buttonSizes.map((size) => [variant, size] as const)))(
    'button %s at size %s renders its classes and names them in data attributes',
    (variant, size) => {
      const button = mount(Button, { props: { variant, size }, slots: { default: 'Go' } }).get('button')
      expect(button.attributes()).toMatchObject({ 'data-slot': 'button', 'data-variant': variant, 'data-size': size })
      // cn() lets the size's text class replace the base one, as the caller's classes would.
      expect(button.classes()).toEqual(classes(cn(buttonVariants({ variant, size }))))
    },
  )

  it.each(badgeVariantNames)('badge %s renders its classes on a span', (variant) => {
    const badge = mount(Badge, { props: { variant }, slots: { default: 'Live' } })
    expect(badge.element.tagName).toBe('SPAN')
    expect(badge.classes()).toEqual(classes(cn(badgeVariants({ variant }))))
  })

  it('a caller class wins over a variant class through cn()', () => {
    const button = mount(Button, { props: { class: 'px-2' } }).get('button')
    expect(button.classes()).toContain('px-2')
    expect(button.classes()).not.toContain('px-6')
  })

  it('card renders every part in order, under its data-slot', () => {
    const card = mount(() =>
      h(Card, () => [
        h(CardHeader, () => [h(CardTitle, () => 'Title'), h(CardDescription, () => 'Text'), h(CardAction, () => 'Act')]),
        h(CardContent, () => 'Body'),
        h(CardFooter, () => 'Foot'),
      ]))
    const slots = card.findAll('[data-slot]').map((part) => part.attributes('data-slot'))
    expect(slots).toEqual(['card', 'card-header', 'card-title', 'card-description', 'card-action', 'card-content', 'card-footer'])
  })
})

describe('accessibility attributes', () => {
  it('button renders a native button, or the element that `as` names', () => {
    expect(mount(Button).element.tagName).toBe('BUTTON')
    const link = mount(Button, { props: { as: 'a' }, attrs: { href: '/next' } })
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('href')).toBe('/next')
  })

  it('a disabled button is disabled for the browser, not only styled', () => {
    expect(mount(Button, { attrs: { disabled: true } }).get('button').element.disabled).toBe(true)
  })

  it('card title is a heading, and card is a div unless `as` names a landmark', () => {
    expect(mount(CardTitle).element.tagName).toBe('H3')
    expect(mount(Card).element.tagName).toBe('DIV')
    expect(mount(Card, { props: { as: 'section' } }).element.tagName).toBe('SECTION')
  })

  it('input passes its label and invalid state to the native field', () => {
    const input = mount(Input, { attrs: { 'aria-label': 'Quiz ID', 'aria-invalid': 'true', 'aria-describedby': 'hint' } }).get('input')
    expect(input.attributes()).toMatchObject({ 'aria-label': 'Quiz ID', 'aria-invalid': 'true', 'aria-describedby': 'hint' })
  })

  it('progress is a progressbar that reports its value against max', () => {
    const bar = mount(Progress, { props: { modelValue: 3, max: 10 }, attrs: { 'aria-label': 'Question 3 of 10' } }).get('[role="progressbar"]')
    expect(bar.attributes()).toMatchObject({ 'aria-valuenow': '3', 'aria-valuemax': '10', 'aria-label': 'Question 3 of 10' })
  })

  it('toaster renders the labelled notification region', () => {
    const toaster = mount(Toaster)
    expect(toaster.get('section').attributes('aria-label')).toMatch(/^Notifications/)
  })
})

describe('Input v-model', () => {
  it('shows the bound value and emits each edit', async () => {
    const input = mount(Input, { props: { modelValue: 'VOCAB', 'onUpdate:modelValue': (value: string | number) => input.setProps({ modelValue: value }) } })
    expect(input.get('input').element.value).toBe('VOCAB')
    await input.get('input').setValue('VOCAB-42')
    expect(input.emitted('update:modelValue')).toEqual([['VOCAB-42']])
    expect(input.props('modelValue')).toBe('VOCAB-42')
  })

  it('follows a new bound value from the parent', async () => {
    const input = mount(Input, { props: { modelValue: 'a' } })
    await input.setProps({ modelValue: 'b' })
    expect(input.get('input').element.value).toBe('b')
  })

  it('starts from defaultValue when nothing is bound', () => {
    expect(mount(Input, { props: { defaultValue: 'draft' } }).get('input').element.value).toBe('draft')
  })
})
