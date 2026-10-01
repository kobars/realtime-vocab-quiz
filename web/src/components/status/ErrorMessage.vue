<!-- AI-ASSISTED: one short, plain message per error the player can hit; SESSION_REPLACED stays, with "Use this tab" (UI spec §3.7, §4.3). -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import type { ErrorCode } from '@/protocol/types.generated'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

/** How long a message the client recovers from by itself stays visible. */
const HIDE_AFTER_MS = 6_000

const store = useQuizStore()
const code = ref<ErrorCode | null>(null)
const button = useTemplateRef<{ $el: HTMLElement }>('button')
let timer: ReturnType<typeof setTimeout> | undefined

const text = (c: ErrorCode): string => (c in strings.errors ? strings.errors[c as keyof typeof strings.errors] : strings.errors.other)

watch(() => store.lastError, (error) => {
  clearTimeout(timer)
  code.value = error?.code ?? null
  if (code.value === 'SESSION_REPLACED') void nextTick(() => button.value?.$el.focus())
  else if (code.value !== null) timer = setTimeout(() => (code.value = null), HIDE_AFTER_MS)
})
onBeforeUnmount(() => clearTimeout(timer))

/** A new ticket and `join` from this tab; the other tab then gets this message. */
function useThisTab(): void {
  const quiz = store.quiz
  code.value = null
  if (quiz) store.join(quiz.quizId, quiz.displayName)
}
</script>

<template>
  <div
    v-if="code === 'SESSION_REPLACED'"
    role="alert"
    data-test="error"
    class="flex flex-col items-start gap-3 rounded-lg bg-card p-4 shadow-card"
  >
    <p class="font-semibold">
      {{ text(code) }}
    </p>
    <Button
      ref="button"
      @click="useThisTab"
    >
      {{ strings.errors.useThisTab }}
    </Button>
  </div>
  <p
    v-else
    role="status"
    data-test="error"
    :class="code ? 'text-sm text-destructive' : 'sr-only'"
  >
    {{ code ? text(code) : '' }}
  </p>
</template>
