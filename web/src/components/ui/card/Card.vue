<!-- AI-ASSISTED: shadcn-vue card as a clay card: card radius, 3 px outline, hard tinted shadow; `interactive` adds a lift on hover behind motion-safe. -->
<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  class?: HTMLAttributes["class"]
  interactive?: boolean
}>()
</script>

<template>
  <div
    data-slot="card"
    :class="
      cn(
        'bg-card text-card-foreground flex flex-col gap-6 rounded-card border-clay border-border p-6 shadow-clay sm:p-8',
        interactive && 'transition-[box-shadow,transform] duration-slow ease-spring hover:shadow-clay-lift motion-safe:hover:-translate-y-1',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
