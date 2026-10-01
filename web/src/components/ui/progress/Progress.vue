<!-- AI-ASSISTED: shadcn-vue progress bar, changed to fill against max instead of 100. -->
<script setup lang="ts">
import type { ProgressRootProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { computed } from "vue"
import {
  ProgressIndicator,
  ProgressRoot,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = withDefaults(
  defineProps<ProgressRootProps & { class?: HTMLAttributes["class"] }>(),
  {
    modelValue: 0,
  },
)

const delegatedProps = reactiveOmit(props, "class")

// The share of max that is filled, in percent, kept within 0–100.
const percent = computed(() => {
  const max = props.max ?? 100
  const value = ((props.modelValue ?? 0) / max) * 100
  return Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0))
})
</script>

<template>
  <ProgressRoot
    data-slot="progress"
    v-bind="delegatedProps"
    :class="
      cn(
        'bg-primary/20 relative h-2 w-full overflow-hidden rounded-full',
        props.class,
      )
    "
  >
    <ProgressIndicator
      data-slot="progress-indicator"
      class="bg-primary h-full w-full flex-1 transition-all"
      :style="`transform: translateX(-${100 - percent}%);`"
    />
  </ProgressRoot>
</template>
