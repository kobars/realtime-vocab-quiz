<!-- AI-ASSISTED: the quiz screen after the join: header with progress, score and rank, the connection pill and error messages, then intro, question or results by the client phase (UI spec §2, §3.2, §3.3, §3.6, §3.7). -->
<script setup lang="ts">
import { computed, nextTick, useTemplateRef, watch } from 'vue'
import LeaderboardPanel from '@/components/leaderboard/LeaderboardPanel.vue'
import QuestionCard from '@/components/question/QuestionCard.vue'
import ConnectionBanner from '@/components/status/ConnectionBanner.vue'
import ErrorMessage from '@/components/status/ErrorMessage.vue'
import { Button } from '@/components/ui/button'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import ResultsView from './ResultsView.vue'

defineProps<{ quizId: string }>()

const store = useQuizStore()
const start = useTemplateRef<{ $el: HTMLElement }>('start')
const shownIndex = computed(() => {
  if (store.phase === 'question') return store.question?.questionIndex ?? null
  if (store.phase === 'feedback') return store.lastResult?.questionIndex ?? null
  return null
})

const intro = computed(() => store.quiz !== null && (store.phase === 'intro' || store.phase === 'join'))
watch(intro, (shown) => shown && void nextTick(() => start.value?.$el.focus()), { immediate: true })

/** Another tab took over: its card replaces the quiz column and the leaderboard (UI spec §3.7). */
const replaced = computed(() => store.lastError?.code === 'SESSION_REPLACED')
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h1 class="text-2xl font-semibold">
        {{ strings.quiz.title(quizId) }}
      </h1>
      <p
        v-if="shownIndex !== null && store.quiz"
        data-test="progress"
        class="text-muted-foreground"
      >
        {{ strings.quiz.progress(shownIndex + 1, store.quiz.questionCount) }}
      </p>
      <p class="flex gap-3 font-semibold tabular-nums">
        <span data-test="score">{{ strings.quiz.score(store.myScore) }}</span>
        <span v-if="store.myRank !== null">{{ strings.quiz.rank(store.myRank, store.playerCount) }}</span>
      </p>
      <ConnectionBanner />
    </header>
    <ErrorMessage />
    <ResultsView v-if="store.phase === 'finished' || store.phase === 'results'" />
    <div
      v-else-if="!replaced"
      class="grid gap-6 lg:grid-cols-[minmax(0,640px)_360px] lg:justify-between"
    >
      <QuestionCard
        v-if="store.phase === 'question' && store.question"
        :question="store.question"
      />
      <section
        v-else-if="intro && store.quiz"
        class="flex flex-col items-start gap-3"
      >
        <p>{{ strings.quiz.intro(store.quiz.questionCount, store.quiz.timeLimitMs / 1_000) }}</p>
        <p class="text-muted-foreground">
          {{ strings.quiz.rule }}
        </p>
        <Button
          ref="start"
          @click="store.next()"
        >
          {{ store.quiz.cursor < 0 ? strings.quiz.start : strings.quiz.continue }}
        </Button>
      </section>
      <div v-else />
      <LeaderboardPanel />
    </div>
  </div>
</template>
