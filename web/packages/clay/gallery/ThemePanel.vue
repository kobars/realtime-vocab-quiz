<!-- AI-ASSISTED: one theme's half of a gallery section: its tokens scoped to the panel, on the theme's page colour. -->
<script setup lang="ts">
import { computed } from 'vue'
import { type Theme, themeStyle } from './theme'

const props = defineProps<{ theme: Theme }>()
const style = computed(() => themeStyle(props.theme))
const label = computed(() => (props.theme === 'light' ? 'Light' : 'Dark'))
</script>

<template>
  <div
    :data-theme="theme"
    :style="style"
    class="flex min-w-0 flex-col gap-4 rounded-card border-clay border-border bg-background p-4 text-foreground sm:p-6"
  >
    <h3 class="text-sm font-bold tracking-wide text-muted-foreground uppercase">
      {{ label }}
    </h3>
    <slot />
  </div>
</template>
