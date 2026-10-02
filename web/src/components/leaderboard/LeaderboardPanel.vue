<!-- AI-ASSISTED: the live leaderboard panel: player counts, the top 10, my row pinned below it when I am further down (on an opaque dock that sticks to the bottom of the window while the list scrolls), and "Show all players", whose paged list takes the place of the top 10 while it is open, in a clay card (UI spec §3.5). -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge, Card } from '@quiz/clay'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import AllPlayers from './AllPlayers.vue'
import LeaderboardRows from './LeaderboardRows.vue'
import { TOP_ROWS } from './limits'
import PinnedRow from './PinnedRow.vue'

const store = useQuizStore()
const me = computed(() => store.quiz?.userId ?? null)
// rank_update keeps myRank current above 200 players, where the frames carry only the top 50.
const pinned = computed(() => store.myRank !== null && !store.entries.some((row) => row.userId === me.value && row.rank <= TOP_ROWS))
/** "Show all players" is open: its pages replace the top 10, so no player is listed twice. */
const all = ref(false)
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
    <template v-if="!all">
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
        <PinnedRow />
      </div>
    </template>
    <!-- With every player in the top 10 there is nothing more to show. -->
    <AllPlayers
      v-if="all || store.playerCount > TOP_ROWS"
      v-model:open="all"
    />
  </Card>
</template>
