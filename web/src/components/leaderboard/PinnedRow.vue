<!-- AI-ASSISTED: my row pinned under the top 10 when my rank is further down: a decorative gap mark, then my rank, name and score in the highlighted clay row; it decides from my rank alone, so a join to an ended quiz (no `joined`, no user ID) never pins a row the top 10 already shows (UI spec §3.5, §3.6). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import { TOP_ROWS } from './limits'
import { MY_ROW, placeFill, RANK_CHIP } from './places'

const store = useQuizStore()
// The rank is the header's, and my row in the list always sits at it, so a rank in the top 10 is a row already on screen.
const shown = computed(() => store.myRank !== null && store.myRank > TOP_ROWS)
// A join to an ended quiz binds no `quiz`: my name is then the one on the row at my rank, when the standings carry it.
const name = computed(() => store.quiz?.displayName ?? store.entries.find((row) => row.rank === store.myRank)?.displayName ?? '')
</script>

<template>
  <div
    v-if="shown"
    class="flex flex-col gap-1"
  >
    <span
      aria-hidden="true"
      class="text-center leading-none font-extrabold text-muted-foreground"
    >⋯</span>
    <p
      data-test="pinned"
      class="flex min-h-12 items-center gap-3 rounded-lg px-3 py-1.5"
      :class="MY_ROW"
    >
      <span :class="[RANK_CHIP, placeFill(store.myRank ?? 0)]">#{{ store.myRank }}</span>
      <span class="min-w-0 flex-1 truncate">{{ name }} {{ strings.leaderboard.you }}</span>
      <span class="tabular-nums">{{ store.myScore }}</span>
    </p>
  </div>
</template>
