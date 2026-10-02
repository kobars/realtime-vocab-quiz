<!-- AI-ASSISTED: one specimen of the gallery with its caption: a token, a variant or a state. -->
<script setup lang="ts">
defineProps<{ label: string; detail?: string }>()
</script>

<template>
  <figure class="flex min-w-0 flex-col items-start gap-2">
    <slot />
    <figcaption class="flex flex-col text-sm">
      <span class="font-bold wrap-anywhere">{{ label }}</span>
      <span
        v-if="detail"
        class="text-muted-foreground wrap-anywhere"
      >{{ detail }}</span>
    </figcaption>
  </figure>
</template>
