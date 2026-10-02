<!-- AI-ASSISTED: the quiz screen after the join: header with progress, score and rank, the connection pill and error messages, then intro, question, feedback or results by the client phase, as Quiz and Leaderboard pill tabs on phones, header pills, an intro card, a loading card while a rejoin asks for the open question again, with the score count-up, the answer, rank and countdown announcements, the quiz time left on the intro, and on the phone's Leaderboard tab a time-left button back to the open question (UI spec §2, §3.2–§3.4, §3.6, §3.7, §4.1, §6.1, §6.3). -->
<script setup lang="ts">
import { LoaderCircle, Rocket, Timer } from '@lucide/vue'
import { useIntervalFn, useMediaQuery } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import LeaderboardPanel from '@/components/leaderboard/LeaderboardPanel.vue'
import AnswerFeedback from '@/components/question/AnswerFeedback.vue'
import { useCountdown, useCountUp } from '@/components/question/motion'
import QuestionCard from '@/components/question/QuestionCard.vue'
import ConnectionBanner from '@/components/status/ConnectionBanner.vue'
import ErrorMessage from '@/components/status/ErrorMessage.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import ResultsView from './ResultsView.vue'

defineProps<{ quizId: string }>()

const store = useQuizStore()
// Only a new answer result counts the header score up; `joined`, `snapshot` and the others swap it at once (UI spec §4.3).
let counted = store.lastResult
const score = useCountUp(() => store.myScore, undefined, (to) => {
  const fresh = store.lastResult !== counted && store.lastResult?.score === to
  counted = store.lastResult
  return fresh
})
const start = useTemplateRef<{ $el: HTMLElement }>('start')
const shownIndex = computed(() => {
  if (store.phase === 'question') return store.question?.questionIndex ?? null
  if (store.phase === 'feedback') return store.lastResult?.questionIndex ?? null
  return null
})

// The answer result and the new score, announced once each (UI spec §6.3). The region empties when a question
// opens, so the next result is a change the screen reader announces even when its text is the same.
const announcement = ref('')
watch(() => store.phase === 'question', (open) => open && (announcement.value = ''))
watch(() => store.lastResult, (result) => {
  if (result === null) return
  const answer = store.question?.choices[result.correctChoiceIndex] ?? ''
  const head = result.late ? strings.quiz.late : result.correct ? strings.quiz.announceCorrect(result.pointsAwarded) : strings.quiz.announceWrong(answer)
  announcement.value = strings.quiz.announce(head, result.score)
})

// My rank, announced only when it changes and at most once every 5 s (UI spec §6.3).
const RANK_GAP_MS = 5_000
const rankSpoken = ref('')
let rankTimer: ReturnType<typeof setTimeout> | null = null
let rankDue = false
function sayRank(): void {
  if (store.myRank === null) return
  rankSpoken.value = strings.quiz.announceRank(store.myRank, store.playerCount)
  rankTimer = setTimeout(() => {
    rankTimer = null
    if (!rankDue) return
    rankDue = false
    sayRank()
  }, RANK_GAP_MS)
}
watch(() => store.myRank, () => {
  if (rankTimer === null) sayRank()
  else rankDue = true
})
onBeforeUnmount(() => {
  if (rankTimer !== null) clearTimeout(rankTimer)
})

// The one countdown of the open question: the question card's ring reads it, and so do the phone's time-left button
// and the 10 s and 5 s warnings while the Leaderboard tab hides the question. The warnings live here, outside the tab
// panels, so they are heard on either tab: only when the count crosses them, never every second; a new question (the
// count goes up) clears them (UI spec §6.3). A blocking card ends the question on screen, so it stops all three.
const asking = computed(() => store.phase === 'question' && store.blocked === null)
const msLeft = useCountdown(() => (asking.value ? store.msLeft() : 0), () => (asking.value ? store.question?.deadlineAt : null))
const secondsLeft = computed(() => Math.ceil(msLeft.value / 1_000))
const warned = ref('')
watch(secondsLeft, (now, before) => {
  if (now > before) warned.value = ''
  else if ((before > 10 && now <= 10 && now > 5) || (before > 5 && now <= 5 && now > 0)) warned.value = strings.quiz.secondsLeft(now)
})

// While a question is open the join re-asks for it (UI spec §4.2): no intro, so Continue never sends `cursor`.
const intro = computed(() => store.quiz !== null && !store.quiz.cursorOpen && (store.phase === 'intro' || store.phase === 'join'))
watch(intro, (shown) => shown && void nextTick(() => start.value?.$el.focus()), { immediate: true })
// The join asked for the open question again, and no question is on screen until it arrives.
const loading = computed(() => store.blocked === null && store.quiz?.cursorOpen === true && (store.phase === 'intro' || store.phase === 'join'))

// The quiz time left on the intro, read again each second; display only.
const now = ref(store.now())
useIntervalFn(() => (now.value = store.now()), 1_000)
const quizLeft = computed(() => {
  const seconds = Math.ceil(store.quizMsLeft(now.value) / 1_000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})

// Below Tailwind's `lg` breakpoint (1024 px) the quiz and the leaderboard are two tabs (UI spec §2). Both panels
// stay mounted, so a hidden question keeps its countdown and its pending answer.
const wide = useMediaQuery('(min-width: 64rem)')
const TABS = ['quiz', 'leaderboard'] as const
type Tab = (typeof TABS)[number]
const tabLabels: Record<Tab, string> = { quiz: strings.quiz.tab, leaderboard: strings.leaderboard.title }
const tab = ref<Tab>('quiz')
// With two tabs both arrows go to the other one.
const other = (current: Tab): Tab => (current === 'quiz' ? 'leaderboard' : 'quiz')
const TAB_KEYS: Record<string, (current: Tab) => Tab> = { ArrowRight: other, ArrowLeft: other, Home: () => 'quiz', End: () => 'leaderboard' }
/** Selects a tab and moves the focus to it. */
function selectTab(name: Tab): void {
  tab.value = name
  void nextTick(() => document.getElementById(`tab-${name}`)?.focus())
}
function moveTab(event: KeyboardEvent): void {
  const to = TAB_KEYS[event.key]
  if (to === undefined) return
  event.preventDefault()
  selectTab(to(tab.value))
}
/** The open question is under the Leaderboard tab: the header shows its time left. */
const hiddenQuestion = computed(() => !wide.value && tab.value === 'leaderboard' && asking.value)
const panel = (name: Tab) => (wide.value ? {} : { role: 'tabpanel', 'aria-labelledby': `tab-${name}` })
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <h1 class="text-2xl">
        {{ strings.quiz.title(quizId) }}
      </h1>
      <p class="flex flex-wrap items-center gap-2 tabular-nums">
        <Badge
          v-if="shownIndex !== null && store.quiz"
          data-test="progress"
          variant="secondary"
        >
          {{ strings.quiz.progress(shownIndex + 1, store.quiz.questionCount) }}
        </Badge>
        <!-- A viewer of an ended quiz (`you: null`) is not a player: no score. -->
        <Badge
          v-if="!store.ended || store.myRank !== null"
          data-test="score"
        >
          {{ strings.quiz.score(score) }}
        </Badge>
        <Badge
          v-if="store.myRank !== null"
          data-test="rank"
          variant="mint"
        >
          {{ strings.quiz.rank(store.myRank, store.playerCount) }}
        </Badge>
      </p>
      <Button
        v-if="hiddenQuestion"
        data-test="time-left"
        variant="outline"
        size="sm"
        class="tabular-nums"
        @click="selectTab('quiz')"
      >
        <Timer aria-hidden="true" />
        {{ strings.quiz.timeLeft(secondsLeft) }}
      </Button>
      <ConnectionBanner />
    </header>
    <ErrorMessage />
    <p
      class="sr-only"
      aria-live="polite"
      aria-atomic="true"
      data-test="announce"
    >
      {{ announcement }}
    </p>
    <p
      class="sr-only"
      aria-live="polite"
      aria-atomic="true"
      data-test="rank-announce"
    >
      {{ rankSpoken }}
    </p>
    <p
      class="sr-only"
      aria-live="polite"
      aria-atomic="true"
      data-test="ring-announce"
    >
      {{ warned }}
    </p>
    <!-- The live region stays in the page, so the loading text is announced when it appears. -->
    <p
      class="sr-only"
      role="status"
      data-test="loading-status"
    >
      {{ loading ? strings.quiz.loading : '' }}
    </p>
    <!-- A blocking card replaces the quiz column and the leaderboard, on every phase (UI spec §3.7). -->
    <ResultsView v-if="store.blocked === null && (store.phase === 'finished' || store.phase === 'results')" />
    <div
      v-else-if="store.blocked === null"
      class="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,40rem)_22.5rem] lg:justify-between"
    >
      <div
        v-if="!wide"
        role="tablist"
        class="flex gap-1 rounded-full border-clay bg-muted p-1"
        @keydown="moveTab"
      >
        <Button
          v-for="name in TABS"
          :id="`tab-${name}`"
          :key="name"
          variant="ghost"
          role="tab"
          :data-tab="name"
          :aria-selected="tab === name"
          :aria-controls="`panel-${name}`"
          :tabindex="tab === name ? 0 : -1"
          class="flex-1 rounded-full aria-selected:border-border aria-selected:bg-card aria-selected:text-primary aria-selected:shadow-press"
          @click="tab = name"
        >
          {{ tabLabels[name] }}
        </Button>
      </div>
      <div
        v-show="wide || tab === 'quiz'"
        id="panel-quiz"
        v-bind="panel('quiz')"
      >
        <QuestionCard
          v-if="store.phase === 'question' && store.question"
          :question="store.question"
          :ms-left="msLeft"
        />
        <AnswerFeedback
          v-else-if="store.phase === 'feedback' && store.lastResult && store.question && store.quiz"
          :result="store.lastResult"
          :choices="store.question.choices"
          :question-count="store.quiz.questionCount"
        />
        <Card
          v-else-if="intro && store.quiz"
          as="section"
          class="items-start gap-4"
        >
          <span
            class="flex size-16 items-center justify-center rounded-xl bg-gradient-primary text-primary-foreground"
            aria-hidden="true"
          >
            <Rocket class="size-8" />
          </span>
          <p class="text-xl font-bold">
            {{ strings.quiz.intro(store.quiz.questionCount, store.quiz.timeLimitMs / 1_000) }}
          </p>
          <p
            data-test="quiz-left"
            class="tabular-nums"
          >
            {{ strings.quiz.quizLeft(quizLeft) }}
          </p>
          <p class="text-muted-foreground">
            {{ strings.quiz.rule }}
          </p>
          <Button
            ref="start"
            data-test="start"
            size="lg"
            :aria-disabled="!store.online"
            :aria-busy="store.requested"
            class="aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
            @click="store.next()"
          >
            <LoaderCircle
              v-if="store.requested"
              class="motion-safe:animate-spin"
              aria-hidden="true"
            />
            {{ store.quiz.cursor < 0 ? strings.quiz.start : strings.quiz.continue }}
          </Button>
        </Card>
        <!-- The card holds the question's place; the status region above announces it. -->
        <Card
          v-else-if="loading"
          data-test="loading"
          class="flex-row items-center gap-3"
        >
          <LoaderCircle
            class="size-5 motion-safe:animate-spin"
            aria-hidden="true"
          />
          {{ strings.quiz.loading }}
        </Card>
      </div>
      <div
        v-show="wide || tab === 'leaderboard'"
        id="panel-leaderboard"
        v-bind="panel('leaderboard')"
      >
        <LeaderboardPanel />
      </div>
    </div>
  </div>
</template>
