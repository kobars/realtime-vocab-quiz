<!-- AI-ASSISTED: standings rows in rank order, keyed by userId so a rank change moves the row with a FLIP (UI spec §3.5, §5.1). -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Entry } from '@/protocol/types.generated'
import { strings } from '@/strings'
import { MAX_MOVES, TOP_N } from './limits'

const props = withDefaults(defineProps<{ entries: Entry[]; myUserId?: string | null; limit?: number; animate?: boolean }>(), {
  myUserId: null,
  limit: TOP_N,
  animate: true,
})

const rows = computed(() => [...props.entries].sort((a, b) => a.rank - b.rank).slice(0, props.limit))
const flip = ref(props.animate)
watch(rows, (now, before) => {
  const was = new Map(before.map((row, i) => [row.userId, i]))
  const moves = now.filter((row, i) => was.has(row.userId) && was.get(row.userId) !== i).length
  flip.value = props.animate && moves <= MAX_MOVES
}, { flush: 'pre' })
</script>

<template>
  <TransitionGroup
    tag="ol"
    :name="flip ? 'lb' : 'lb-off'"
    :data-flip="flip"
    class="relative flex flex-col"
  >
    <li
      v-for="row in rows"
      :key="row.userId"
      :data-user="row.userId"
      :aria-current="row.userId === myUserId ? 'true' : undefined"
      class="flex items-center gap-3 rounded-md px-3 py-2"
      :class="{ 'bg-highlight font-semibold': row.userId === myUserId }"
    >
      <span class="w-10 text-muted-foreground tabular-nums">#{{ row.rank }}</span>
      <span class="min-w-0 flex-1 truncate">{{ row.userId === myUserId ? `${row.displayName} ${strings.leaderboard.you}` : row.displayName }}</span>
      <span class="tabular-nums">{{ row.score }}</span>
    </li>
  </TransitionGroup>
</template>

<style scoped>
.lb-move { transition: transform var(--motion-base) var(--ease-standard); }
.lb-enter-active { transition: opacity var(--motion-base) var(--ease-standard); }
.lb-leave-active { position: absolute; inset-inline: 0; transition: opacity var(--motion-fast) var(--ease-standard); }
.lb-enter-from, .lb-leave-to { opacity: 0; }
</style>
