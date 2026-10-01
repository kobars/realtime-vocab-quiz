// @vitest-environment node
// AI-ASSISTED: checks that the ESLint config accepts browser globals in Vue single-file components.
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

describe('eslint config', () => {
  it('accepts browser globals in a .vue file', async () => {
    const eslint = new ESLint()
    const [result] = await eslint.lintText(component, { filePath: 'src/LayoutProbe.vue' })
    expect(result?.messages).toEqual([])
  })
})
