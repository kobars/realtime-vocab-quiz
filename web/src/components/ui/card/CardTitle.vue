<!-- AI-ASSISTED: shadcn-vue card part; a heading in the type scale, weight from the base styles. -->
<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
</script>

<template>
  <h3
    data-slot="card-title"
    :class="cn('text-xl leading-tight', props.class)"
  >
    <slot />
  </h3>
</template>
