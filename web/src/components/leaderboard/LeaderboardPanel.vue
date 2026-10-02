<!-- AI-ASSISTED: the live leaderboard panel: player counts, the top 50, my row pinned below it when I am further down (on an opaque dock that sticks to the bottom of the window while the list scrolls), and the full list, in a clay card (UI spec §3.5). -->
<script setup lang="ts">
import { computed } from 'vue'
import { Badge, Card } from '@quiz/clay'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import AllPlayers from './AllPlayers.vue'
import LeaderboardRows from './LeaderboardRows.vue'
import { TOP_N } from './limits'
import { MY_ROW, placeFill, RANK_CHIP } from './places'

const store = useQuizStore()
const me = computed(() => store.quiz?.userId ?? null)
// rank_update keeps myRank current above 200 players, where the frames carry only the top 50.
const pinned = computed(() => store.myRank !== null && !store.entries.some((row) => row.userId === me.value && row.rank <= TOP_N))
</script>

<template>
  <Card
    as="section"
    class="gap-4"
    :aria-label="strings.leaderboard.title"
  >
    <header class="flex flex-wrap items-center justify-between gap-2">
      <h2 class="text-xl">
        {{ strings.leaderboard.title }}
      </h2>
      <span
        v-if="store.connection === 'resyncing'"
        role="status"
        class="text-sm text-muted-foreground"
      >{{ strings.leaderboard.updating }}</span>
      <Badge
        data-test="counts"
        variant="cyan"
        class="tabular-nums"
      >
        {{ strings.leaderboard.counts(store.playerCount, store.onlineCount) }}
      </Badge>
    </header>
    <LeaderboardRows
      :entries="store.entries"
      :my-user-id="me"
      :replacements="store.replacements"
    />
    <!-- The dock is opaque card colour around my row, so a row scrolling under it is hidden behind a clean edge instead of showing beside or through it. Its padding replaces the card's gap on either side. -->
    <div
      v-if="pinned"
      data-test="pinned-dock"
      class="sticky bottom-0 z-1 -my-2 bg-card py-2"
    >
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
    <AllPlayers />
  </Card>
</template>
