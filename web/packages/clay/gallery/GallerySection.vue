<!-- AI-ASSISTED: a gallery section: a heading, a note and the same specimens in the light and the dark theme, side by side from 1024 px. -->
<script setup lang="ts">
import ThemePanel from './ThemePanel.vue'
import { THEMES, type Theme } from './theme'

defineProps<{ id: string; title: string }>()
defineSlots<{ default: (props: { theme: Theme }) => unknown; note?: () => unknown }>()
</script>

<template>
  <section
    :id="id"
    :aria-labelledby="`${id}-title`"
    class="flex scroll-mt-4 flex-col gap-4"
  >
    <h2
      :id="`${id}-title`"
      class="text-2xl"
    >
      {{ title }}
    </h2>
    <p
      v-if="$slots.note"
      class="max-w-prose text-muted-foreground"
    >
      <slot name="note" />
    </p>
    <div class="grid gap-4 lg:grid-cols-2">
      <ThemePanel
        v-for="theme in THEMES"
        :key="theme"
        :theme="theme"
      >
        <slot :theme="theme" />
      </ThemePanel>
    </div>
  </section>
</template>
