<!-- AI-ASSISTED: the podium of the final results: ranks 1–3, first place in the middle and highest, clay steps on the role fills with decorative medals, rising once in turn behind motion-safe (UI spec §3.6, §5.5). -->
<script setup lang="ts">
import { computed } from 'vue'
import type { Entry } from '@/protocol/types.generated'
import { placeFill } from './places'

const props = defineProps<{ entries: Entry[] }>()

const HEIGHT: Record<number, string> = { 1: 'h-32 sm:h-40', 2: 'h-24 sm:h-30', 3: 'h-20 sm:h-25' }
const MEDAL: Record<number, string> = { 1: '🥇', 2: '🥈', 3: '🥉' }
// Third place rises first, then second, then first.
const DELAY: Record<number, string> = { 1: 'rise-delay-2', 2: 'rise-delay-1', 3: 'rise-delay-0' }
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
      class="flex w-24 min-w-0 flex-col items-center gap-1 text-center motion-safe:animate-rise sm:w-28"
      :class="[ORDER[step.rank], DELAY[step.rank]]"
    >
      <span
        class="text-2xl"
        aria-hidden="true"
      >{{ MEDAL[step.rank] }}</span>
      <span
        class="w-full truncate font-bold"
        :title="step.displayName"
      >{{ step.displayName }}</span>
      <span class="text-sm font-semibold text-muted-foreground tabular-nums">{{ step.score }}</span>
      <span
        class="flex w-full items-start justify-center rounded-t-xl border-clay border-b-0 pt-2 text-2xl font-extrabold"
        :class="[HEIGHT[step.rank], placeFill(step.rank)]"
      >{{ step.rank }}</span>
    </li>
  </ol>
</template>
