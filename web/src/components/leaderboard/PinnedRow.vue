<!-- AI-ASSISTED: my row pinned under the top 10 when I am further down: a decorative gap mark, then my rank, name and score in the highlighted clay row (UI spec §3.5, §3.6). -->
<script setup lang="ts">
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import { MY_ROW, placeFill, RANK_CHIP } from './places'

const store = useQuizStore()
</script>

<template>
  <div class="flex flex-col gap-1">
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
      <span class="min-w-0 flex-1 truncate">{{ store.quiz?.displayName }} {{ strings.leaderboard.you }}</span>
      <span class="tabular-nums">{{ store.myScore }}</span>
    </p>
  </div>
</template>
