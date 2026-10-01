<!-- AI-ASSISTED: the finished and results screens: a provisional rank and the live board until the end, then the podium, my final rank and the top 50 (UI spec §3.6). -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import AllPlayers from '@/components/leaderboard/AllPlayers.vue'
import LeaderboardPanel from '@/components/leaderboard/LeaderboardPanel.vue'
import LeaderboardRows from '@/components/leaderboard/LeaderboardRows.vue'
import ResultsPodium from '@/components/leaderboard/ResultsPodium.vue'
import { Badge } from '@/components/ui/badge'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const store = useQuizStore()
const heading = useTemplateRef<HTMLElement>('heading')
const podium = computed(() => store.entries.filter((row) => row.rank <= 3))
const rest = computed(() => store.entries.filter((row) => row.rank > 3))
const focusHeading = () => void nextTick(() => heading.value?.focus())
onMounted(focusHeading)
watch(() => store.ended, focusHeading)

// The countdown to the quiz end, read again each second; display only.
const msLeft = ref(store.quizMsLeft())
const timer = setInterval(() => (msLeft.value = store.quizMsLeft()), 1_000)
onBeforeUnmount(() => clearInterval(timer))
const timeLeft = computed(() => {
  const seconds = Math.ceil(msLeft.value / 1_000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
</script>

<template>
  <section
    v-if="store.ended"
    class="flex flex-col gap-6"
  >
    <h2
      ref="heading"
      tabindex="-1"
      class="text-2xl font-semibold"
    >
      {{ strings.results.title }}
    </h2>
    <ResultsPodium :entries="podium" />
    <div
      v-if="store.myRank !== null"
      data-test="my-result"
      class="rounded-lg bg-card p-4 shadow-card"
    >
      <p class="font-semibold">
        {{ strings.results.placed(store.myRank, store.playerCount) }}
      </p>
      <p class="tabular-nums text-muted-foreground">
        {{ strings.results.points(store.myScore) }}
      </p>
    </div>
    <LeaderboardRows
      :entries="rest"
      :my-user-id="store.quiz?.userId"
    />
    <AllPlayers />
  </section>
  <section
    v-else
    class="flex flex-col gap-6"
  >
    <div
      data-test="my-result"
      class="flex flex-col gap-1 rounded-lg bg-card p-4 shadow-card"
    >
      <h2
        ref="heading"
        tabindex="-1"
        class="text-2xl font-semibold"
      >
        {{ strings.results.finished }}
      </h2>
      <p class="tabular-nums">
        {{ strings.results.points(store.myScore) }}
      </p>
      <p
        v-if="store.myRank !== null"
        class="flex items-center gap-2"
      >
        {{ strings.results.rank(store.myRank, store.playerCount) }}
        <Badge variant="secondary">
          {{ strings.results.provisional }}
        </Badge>
      </p>
      <p class="text-sm text-muted-foreground">
        {{ strings.results.canChange(timeLeft) }}
      </p>
    </div>
    <LeaderboardPanel />
  </section>
</template>
