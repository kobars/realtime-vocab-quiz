<!-- AI-ASSISTED: the question screen: the countdown, the prompt and four choices (click or keys 1–4 while shown), locked while an answer is pending or the socket is down, and Skip, locked while the socket is down; clay choice tiles that lift and press behind motion-safe (UI spec §3.3, §4.1, §5.5, §6.1, §6.2). -->
<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { useEventListener } from '@vueuse/core'
import { computed, nextTick, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import type { CurrentQuestion } from '@/stores/quiz'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import CountdownRing from './CountdownRing.vue'
import { useCountdown } from './motion'

const props = defineProps<{ question: CurrentQuestion }>()
/** The key hint chips cycle the role fills; the number stays the cue, the color only tells the keys apart. */
const KEY_FILLS = ['bg-input', 'bg-mint', 'bg-cyan', 'bg-sun'] as const
const store = useQuizStore()
const heading = useTemplateRef<HTMLElement>('heading')
const msLeft = useCountdown(() => store.msLeft(), () => props.question.deadlineAt)
// `resyncing` is a healthy socket: requests go out at once (UI spec §4.1).
const online = computed(() => store.connection === 'joined' || store.connection === 'resyncing')
const locked = computed(() => store.pending !== null || !online.value)
// Only a link that is coming back says so; after a final close or an unknown quiz no reconnect follows (UI spec §3.3).
const waiting = computed(() => store.connection === 'connecting' || store.connection === 'reconnecting')

watch(() => props.question.questionIndex, () => void nextTick(() => heading.value?.focus()), { immediate: true })

function choose(choiceIndex: number): void {
  if (!locked.value) store.answer(choiceIndex)
}

// The client drops a `next` sent while the socket is down, so Skip waits for it (UI spec §4.1).
function skip(): void {
  if (online.value) store.next()
}

// Keys 1–4 choose, unless a text field has the focus, a modifier is held or the phone's Leaderboard tab hides the question.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  const target = event.target instanceof Element ? event.target : null
  if (event.ctrlKey || event.metaKey || event.altKey || target?.closest('input, textarea, select, [contenteditable]')) return
  if (heading.value?.checkVisibility() === false) return
  const n = Number(event.key)
  if (Number.isInteger(n) && n >= 1 && n <= 4) {
    event.preventDefault()
    choose(n - 1)
  }
})
</script>

<template>
  <section class="flex flex-col gap-4">
    <div class="flex items-center gap-4">
      <h2
        ref="heading"
        tabindex="-1"
        class="flex-1 text-2xl sm:text-title"
      >
        {{ question.prompt }}
      </h2>
      <CountdownRing
        :ms-left="msLeft"
        :total-ms="question.timeLimitMs"
      />
    </div>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <button
        v-for="(choice, i) in question.choices"
        :key="i"
        type="button"
        :data-choice="i"
        :aria-disabled="locked"
        class="flex min-h-14 items-center gap-3 rounded-lg border-clay bg-card px-4 py-3 text-left text-xl font-semibold shadow-press transition-[background-color,border-color,box-shadow,transform] duration-fast ease-spring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none not-aria-disabled:hover:shadow-press-hover not-aria-disabled:active:shadow-press-active motion-safe:not-aria-disabled:hover:-translate-y-0.5 motion-safe:not-aria-disabled:active:translate-y-0.5 aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
        :class="store.pending?.choiceIndex === i ? 'border-primary bg-highlight' : 'border-input'"
        @click="choose(i)"
      >
        <kbd
          class="flex size-8 shrink-0 items-center justify-center rounded-xl border-2 border-night/10 font-sans text-base font-extrabold text-night"
          :class="KEY_FILLS[i % KEY_FILLS.length]"
        >{{ i + 1 }}</kbd>
        <span class="flex-1">{{ choice }}</span>
        <span
          v-if="store.pending?.choiceIndex === i"
          class="flex items-center gap-1 text-sm text-muted-foreground"
        >
          <LoaderCircle
            class="size-4 motion-safe:animate-spin"
            aria-hidden="true"
          />{{ strings.quiz.checking }}
        </span>
      </button>
    </div>
    <p
      v-if="waiting"
      class="text-sm text-muted-foreground"
    >
      {{ strings.quiz.waiting }}
    </p>
    <div
      v-if="msLeft === 0"
      data-test="time-up"
      class="flex items-center justify-between gap-3"
    >
      <p class="text-sm">
        {{ strings.quiz.timeUp }}
      </p>
      <Button
        v-if="store.pending === null"
        variant="outline"
        :aria-disabled="!online"
        class="aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
        @click="skip"
      >
        {{ strings.quiz.skip }}
      </Button>
    </div>
  </section>
</template>
