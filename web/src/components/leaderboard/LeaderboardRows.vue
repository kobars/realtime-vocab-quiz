<!-- AI-ASSISTED: standings rows in rank order, keyed by userId so a rank change moves the row with a FLIP; full replacements swap in one step, and my row rising gets a 1 s tint; clay rows with a rank chip on the role fills for the top 3 (UI spec §3.5, §5.1). -->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Entry } from '@/protocol/types.generated'
import { strings } from '@/strings'
import { MAX_MOVES, TOP_N } from './limits'
import { MY_ROW, placeFill, RANK_CHIP } from './places'

/** `replacements` counts the full replacements (`snapshot`, `rebase: true`); a change of it swaps the rows in one step. */
const props = withDefaults(defineProps<{ entries: Entry[]; myUserId?: string | null; limit?: number; animate?: boolean; replacements?: number }>(), {
  myUserId: null,
  limit: TOP_N,
  animate: true,
  replacements: 0,
})

const RISE_MS = 1_000
const rows = computed(() => [...props.entries].sort((a, b) => a.rank - b.rank).slice(0, props.limit))
const flip = ref(props.animate)
const rising = ref(false)
let riseTimer: ReturnType<typeof setTimeout> | undefined
watch([rows, () => props.replacements], ([now, replaced], [before, wasReplaced]) => {
  const was = new Map(before.map((row, i) => [row.userId, i]))
  const moves = now.filter((row, i) => was.has(row.userId) && was.get(row.userId) !== i).length
  flip.value = props.animate && replaced === wasReplaced && moves <= MAX_MOVES
  const mine = (list: Entry[]) => list.find((row) => row.userId === props.myUserId)?.rank ?? Infinity
  if (props.animate && props.myUserId !== null && mine(now) < mine(before) && mine(before) !== Infinity) {
    rising.value = true
    clearTimeout(riseTimer)
    riseTimer = setTimeout(() => (rising.value = false), RISE_MS)
  }
}, { flush: 'pre' })
onBeforeUnmount(() => clearTimeout(riseTimer))

// A leaving row is taken out of the flow; its top keeps it where it was while it fades (UI spec §5.1).
const pin = (el: Element): void => void ((el as HTMLElement).style.top = `${(el as HTMLElement).offsetTop}px`)
</script>

<template>
  <TransitionGroup
    tag="ol"
    :name="flip ? 'lb' : 'lb-off'"
    :data-flip="flip"
    class="relative flex flex-col gap-2"
    @before-leave="pin"
  >
    <li
      v-for="row in rows"
      :key="row.userId"
      :data-user="row.userId"
      :aria-current="row.userId === myUserId ? 'true' : undefined"
      class="flex min-h-12 items-center gap-3 rounded-lg px-3 py-1.5"
      :class="[row.userId === myUserId ? MY_ROW : 'border-2 border-border bg-card', { 'lb-rise': rising && row.userId === myUserId }]"
    >
      <span :class="[RANK_CHIP, placeFill(row.rank)]">#{{ row.rank }}</span>
      <span
        class="min-w-0 flex-1 truncate"
        :title="row.displayName"
      >{{ row.userId === myUserId ? `${row.displayName} ${strings.leaderboard.you}` : row.displayName }}</span>
      <span class="font-semibold tabular-nums">{{ row.score }}</span>
    </li>
  </TransitionGroup>
</template>

<style scoped>
.lb-move { transition: transform var(--motion-base) var(--ease-standard); }
.lb-enter-active { transition: opacity var(--motion-base) var(--ease-standard); }
.lb-leave-active { position: absolute; inset-inline: 0; transition: opacity var(--motion-fast) var(--ease-standard); }
.lb-enter-from, .lb-leave-to { opacity: 0; }
/* My row is already tinted; rising, it starts from a stronger tint and fades back to it. */
.lb-rise { animation: lb-rise 1s var(--ease-standard); }
@keyframes lb-rise { from { background-color: color-mix(in srgb, var(--highlight), var(--primary) 20%); } }
@media (prefers-reduced-motion: reduce) { .lb-rise { animation: none; } }
</style>
