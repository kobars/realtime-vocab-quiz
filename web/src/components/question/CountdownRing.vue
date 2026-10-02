<!-- AI-ASSISTED: the countdown ring: a shrinking stroke with the whole seconds left in its center; the warning stroke on a warning track in the last 5 s; a live region that speaks at 10 s and 5 s left (UI spec §5.3, §5.4, §6.3). -->
<script setup lang="ts">
import { usePreferredReducedMotion } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { strings } from '@/strings'

const props = defineProps<{ msLeft: number; totalMs: number }>()
const RADIUS = 32
const LENGTH = 2 * Math.PI * RADIUS
const reduced = usePreferredReducedMotion()
const seconds = computed(() => Math.ceil(props.msLeft / 1_000))
// Reduced motion: the stroke moves once per second, in steps.
const shown = computed(() => (reduced.value === 'reduce' ? seconds.value * 1_000 : props.msLeft))
const offset = computed(() => LENGTH * (1 - Math.min(1, shown.value / props.totalMs)))
/** The last 5 s. */
const warning = computed(() => props.msLeft <= 5_000)

// Spoken only when the count crosses 10 s and 5 s, never every second; a new deadline (the count goes up) clears it.
const spoken = ref('')
watch(seconds, (now, before) => {
  if (now > before) spoken.value = ''
  else if ((before > 10 && now <= 10 && now > 5) || (before > 5 && now <= 5 && now > 0)) spoken.value = strings.quiz.secondsLeft(now)
})
</script>

<template>
  <div
    role="img"
    :aria-label="strings.quiz.secondsLeft(seconds)"
    data-test="ring"
    class="relative size-18 shrink-0 sm:size-22"
  >
    <svg
      viewBox="0 0 72 72"
      class="size-full -rotate-90"
      aria-hidden="true"
    >
      <circle
        cx="36"
        cy="36"
        :r="RADIUS"
        fill="none"
        stroke-width="8"
        data-test="ring-track"
        :class="warning ? 'stroke-warning-soft' : 'stroke-muted'"
      />
      <circle
        cx="36"
        cy="36"
        :r="RADIUS"
        fill="none"
        stroke-width="8"
        stroke-linecap="round"
        data-test="ring-stroke"
        :stroke-dasharray="LENGTH"
        :stroke-dashoffset="offset"
        :class="warning ? 'stroke-warning' : 'stroke-primary'"
      />
    </svg>
    <span class="absolute inset-0 flex items-center justify-center text-2xl font-extrabold tabular-nums">{{ seconds }}</span>
  </div>
  <!-- Outside the image, whose children are presentational. -->
  <span
    class="sr-only"
    aria-live="polite"
    aria-atomic="true"
    data-test="ring-announce"
  >{{ spoken }}</span>
</template>
