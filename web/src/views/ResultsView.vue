<!-- AI-ASSISTED: the finished and results screens: a provisional rank and the live board until the end, with my score and rank in live regions, then the podium, my final rank in a highlighted clay card and the top 50 under a gradient heading (UI spec §3.6, §6.3). -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import AllPlayers from '@/components/leaderboard/AllPlayers.vue'
import LeaderboardPanel from '@/components/leaderboard/LeaderboardPanel.vue'
import LeaderboardRows from '@/components/leaderboard/LeaderboardRows.vue'
import ResultsPodium from '@/components/leaderboard/ResultsPodium.vue'
import { TOP_N } from '@/components/leaderboard/limits'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const store = useQuizStore()
const heading = useTemplateRef<HTMLElement>('heading')
const podium = computed(() => store.entries.filter((row) => row.rank <= 3))
// An ended snapshot carries every player up to 200; the list stops at the top 50.
const rest = computed(() => store.entries.filter((row) => row.rank > 3 && row.rank <= TOP_N))
const focusHeading = () => void nextTick(() => heading.value?.focus())
onMounted(focusHeading)
watch(() => store.ended, focusHeading)

// The countdown to the quiz end, read again each second; display only.
const msLeft = ref(store.quizMsLeft())
const timer = setInterval(() => (msLeft.value = store.quizMsLeft()), 1_000)
onBeforeUnmount(() => clearInterval(timer))

// The rank announced in the live region: on a change, at most once every 5 s, then the latest (UI spec §6.3).
const RANK_ANNOUNCE_MS = 5_000
const rankText = () => (store.myRank === null ? '' : strings.results.rankLive(store.myRank, store.playerCount))
const rankAnnounced = ref(rankText())
let cooldown: ReturnType<typeof setTimeout> | null = null
function announceRank(): void {
  if (cooldown !== null || rankText() === rankAnnounced.value) return
  rankAnnounced.value = rankText()
  cooldown = setTimeout(() => {
    cooldown = null
    announceRank()
  }, RANK_ANNOUNCE_MS)
}
watch(rankText, announceRank)
onBeforeUnmount(() => cooldown !== null && clearTimeout(cooldown))
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
      class="text-gradient text-title sm:text-display"
    >
      {{ strings.results.title }}
    </h2>
    <ResultsPodium :entries="podium" />
    <Card
      v-if="store.myRank !== null"
      data-test="my-result"
      class="gap-2 bg-highlight"
    >
      <p class="text-2xl font-extrabold tabular-nums sm:text-display">
        {{ strings.results.placed(store.myRank, store.playerCount) }}
      </p>
      <p class="text-xl font-bold tabular-nums">
        {{ strings.results.points(store.myScore) }}
      </p>
    </Card>
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
    <Card
      data-test="my-result"
      class="gap-2"
    >
      <h2
        ref="heading"
        tabindex="-1"
        class="text-title"
      >
        {{ strings.results.finished }}
      </h2>
      <p
        class="tabular-nums"
        aria-live="polite"
        aria-atomic="true"
      >
        {{ strings.results.points(store.myScore) }}
      </p>
      <p
        class="sr-only"
        aria-live="polite"
        aria-atomic="true"
      >
        {{ rankAnnounced }}
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
    </Card>
    <LeaderboardPanel />
  </section>
</template>
