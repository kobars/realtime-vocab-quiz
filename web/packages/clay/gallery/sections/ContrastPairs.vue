<!-- AI-ASSISTED: every token pair the components draw, rendered, with its WCAG ratio against the minimum it must reach. -->
<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '../../src'
import { contrast, CONTRAST_PAIRS, MIN_TEXT, themes } from '../../src/tokens'
import { ratio, type Theme } from '../theme'

const props = defineProps<{ theme: Theme }>()
const pairs = computed(() =>
  CONTRAST_PAIRS.map((pair) => {
    const value = contrast(themes[props.theme][pair.fg] ?? '', themes[props.theme][pair.bg] ?? '')
    return { ...pair, text: pair.min >= MIN_TEXT, value, passes: value >= pair.min }
  }))
</script>

<template>
  <ul class="flex flex-col gap-3">
    <li
      v-for="pair in pairs"
      :key="`${pair.fg} ${pair.bg}`"
      class="flex flex-wrap items-center gap-3"
    >
      <!-- Text pairs show text; outline and ring pairs (3:1) show an outline, which is what they are measured as. -->
      <span
        v-if="pair.text"
        class="inline-flex size-11 shrink-0 items-center justify-center rounded-lg border-2 border-border font-bold"
        :style="{ color: `var(${pair.fg})`, background: `var(${pair.bg})` }"
      >Aa</span>
      <span
        v-else
        class="inline-flex size-11 shrink-0 items-center justify-center rounded-lg border-2 border-border"
        :style="{ background: `var(${pair.bg})` }"
        aria-hidden="true"
      >
        <span
          class="size-6 rounded-sm border-clay"
          :style="{ borderColor: `var(${pair.fg})` }"
        />
      </span>
      <span class="min-w-0 flex-1 text-sm">
        <span class="block font-bold wrap-anywhere">{{ pair.fg }} on {{ pair.bg }}</span>
        <span class="text-muted-foreground">{{ ratio(pair.value) }}, needs {{ pair.min }}:1 ({{ pair.text ? 'text' : 'outline' }})</span>
      </span>
      <Badge :variant="pair.passes ? 'success' : 'destructive'">
        {{ pair.passes ? 'Pass' : 'Fail' }}
      </Badge>
    </li>
  </ul>
</template>
