<!-- AI-ASSISTED: a short message for the errors the player should see, and the blocking card for the store's blocked state: "Use this tab" or "Reload" (UI spec §3.7, §4.3). -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

/** How long a message the client recovers from by itself stays visible. */
const HIDE_AFTER_MS = 6_000

type Notice = keyof typeof strings.errors
const isNotice = (code: string): code is Notice => Object.hasOwn(strings.errors, code)

const store = useQuizStore()
const notice = ref<Notice | null>(null)
const button = useTemplateRef<{ $el: HTMLElement }>('button')
let timer: ReturnType<typeof setTimeout> | undefined

watch(() => store.lastError, (error) => {
  clearTimeout(timer)
  notice.value = error !== null && isNotice(error.code) ? error.code : null
  if (notice.value !== null) timer = setTimeout(() => (notice.value = null), HIDE_AFTER_MS)
})
// The card reads the store, so a screen mounted after the error shows it too.
watch(() => store.blocked, (blocked) => blocked !== null && void nextTick(() => button.value?.$el.focus()), { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))

/** "Use this tab": a new ticket and `join` from this tab, and the other tab gets the card. "Reload": the new version. */
function act(): void {
  const quiz = store.quiz
  if (store.blocked === 'version') window.location.reload()
  else if (quiz) store.join(quiz.quizId, quiz.displayName)
}
</script>

<template>
  <div
    v-if="store.blocked"
    role="alert"
    data-test="error"
    class="flex flex-col items-start gap-3 rounded-lg bg-card p-4 shadow-card"
  >
    <p class="font-semibold">
      {{ strings.blocked[store.blocked].title }}
    </p>
    <Button
      ref="button"
      @click="act"
    >
      {{ strings.blocked[store.blocked].action }}
    </Button>
  </div>
  <p
    v-else
    role="status"
    data-test="error"
    :class="notice ? 'text-sm text-destructive' : 'sr-only'"
  >
    {{ notice ? strings.errors[notice] : '' }}
  </p>
</template>
