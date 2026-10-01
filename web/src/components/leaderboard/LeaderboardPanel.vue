<!-- AI-ASSISTED: the live leaderboard panel: player counts, the top 50, my row pinned below it when I am further down, and the full list (UI spec §3.5). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import AllPlayers from './AllPlayers.vue'
import LeaderboardRows from './LeaderboardRows.vue'
import { TOP_N } from './limits'

const store = useQuizStore()
const me = computed(() => store.quiz?.userId ?? null)
// rank_update keeps myRank current above 200 players, where the frames carry only the top 50.
const pinned = computed(() => store.myRank !== null && !store.entries.some((row) => row.userId === me.value && row.rank <= TOP_N))
</script>

<template>
  <section
    class="flex flex-col gap-3"
    :aria-label="strings.leaderboard.title"
  >
    <header class="flex items-baseline justify-between gap-2">
      <h2 class="text-lg font-semibold">
        {{ strings.leaderboard.title }}
      </h2>
      <span
        v-if="store.connection === 'resyncing'"
        role="status"
        class="text-sm text-muted-foreground"
      >{{ strings.leaderboard.updating }}</span>
      <span
        data-test="counts"
        class="text-sm text-muted-foreground tabular-nums"
      >{{ strings.leaderboard.counts(store.playerCount, store.onlineCount) }}</span>
    </header>
    <LeaderboardRows
      :entries="store.entries"
      :my-user-id="me"
    />
    <p
      v-if="pinned"
      data-test="pinned"
      class="flex items-center gap-3 rounded-md border-t bg-highlight px-3 py-2 font-semibold"
    >
      <span class="w-10 tabular-nums">#{{ store.myRank }}</span>
      <span class="min-w-0 flex-1 truncate">{{ store.quiz?.displayName }} {{ strings.leaderboard.you }}</span>
      <span class="tabular-nums">{{ store.myScore }}</span>
    </p>
    <AllPlayers />
  </section>
</template>
