<!-- AI-ASSISTED: the podium of the final results: ranks 1–3, first place in the middle and highest (UI spec §3.6). -->
<script setup lang="ts">
import { computed } from 'vue'
import type { Entry } from '@/protocol/types.generated'

const props = defineProps<{ entries: Entry[] }>()

const HEIGHT: Record<number, string> = { 1: 'h-32', 2: 'h-24', 3: 'h-16' }
// The DOM keeps rank order, so assistive tech reads first place first; CSS order shows second, first, third.
const ORDER: Record<number, string> = { 1: 'order-2', 2: 'order-1', 3: 'order-3' }
// With fewer than 3 players only the steps that exist.
const steps = computed(() => [1, 2, 3].flatMap((rank) => props.entries.filter((row) => row.rank === rank)))
</script>

<template>
  <ol class="flex items-end justify-center gap-3">
    <li
      v-for="step in steps"
      :key="step.userId"
      :data-rank="step.rank"
      class="flex w-28 flex-col items-center gap-1 text-center"
      :class="ORDER[step.rank]"
    >
      <span class="w-full truncate font-semibold">{{ step.displayName }}</span>
      <span class="text-sm tabular-nums text-muted-foreground">{{ step.score }}</span>
      <span
        class="flex w-full items-start justify-center rounded-t-lg bg-primary pt-2 text-2xl font-semibold text-primary-foreground"
        :class="HEIGHT[step.rank]"
      >{{ step.rank }}</span>
    </li>
  </ol>
</template>
