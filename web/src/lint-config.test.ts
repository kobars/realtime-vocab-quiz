// @vitest-environment node
// AI-ASSISTED: checks that the ESLint config accepts browser globals in Vue single-file components and runs the type-aware rules.
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

describe('eslint config', () => {
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
})
