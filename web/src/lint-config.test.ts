// @vitest-environment node
// AI-ASSISTED: checks that the ESLint config accepts browser globals in Vue single-file components, runs the type-aware rules and keeps the app on the design system's public entry points.
import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

const component = `<script setup lang="ts">
const root: HTMLElement | null = document.getElementById('app')
window.addEventListener('resize', () => {
  console.info(root?.clientWidth)
})
</script>

<template>
  <div />
</template>
`

const typed = `type Message = { type: 'a' } | { type: 'b' }
export function receive(message: Message): void {
  switch (message.type) {
    case 'a':
      return
    default:
      return
  }
}
const load = async (): Promise<void> => {}
load()
export const handler: () => void = load
await 1
`

// The project service only types files that the tsconfig includes, so the text lints under existing paths.
async function lint(code: string, filePath: string): Promise<ESLint.LintResult['messages']> {
  const [result] = await new ESLint().lintText(code, { filePath })
  return result?.messages ?? []
}

// The first type-aware lint builds the TypeScript program, which takes several seconds on CI.
describe('eslint config', { timeout: 30_000 }, () => {
  it('accepts browser globals in a .vue file', async () => {
    expect(await lint(component, 'src/App.vue')).toEqual([])
  })

  it('reports an unhandled union member and promise misuse', async () => {
    const rules = (await lint(typed, 'src/main.ts')).map((message) => message.ruleId)
    expect(rules).toEqual([
      '@typescript-eslint/switch-exhaustiveness-check',
      '@typescript-eslint/no-floating-promises',
      '@typescript-eslint/no-misused-promises',
      '@typescript-eslint/await-thenable',
    ])
  })

  it.each([
    "import { Button } from '@quiz/clay/src/components/button'",
    "import { cn } from '../packages/clay/src/utils'",
    "import { cva } from 'class-variance-authority'",
    "import { toast } from 'vue-sonner'",
  ])('rejects %s in app code', async (line) => {
    const rules = (await lint(`${line}\nexport const used = [${line.match(/\{ (\w+) \}/)?.[1]}]\n`, 'src/main.ts')).map((message) => message.ruleId)
    expect(rules).toEqual(['no-restricted-imports'])
  })

  it.each([
    "import { Button, cn } from '@quiz/clay'",
    "import { themes } from '@quiz/clay/tokens'",
    "import { stackedFocusClasses } from '@quiz/clay/testing'",
  ])('accepts %s in app code', async (line) => {
    expect(await lint(`${line}\nexport const used = [${line.match(/\{ ([\w, ]+) \}/)?.[1]}]\n`, 'src/main.ts')).toEqual([])
  })
})
