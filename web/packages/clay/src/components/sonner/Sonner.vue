<!-- AI-ASSISTED: shadcn-vue toaster in the clay look: card radius, 3 px outline, hard shadow, the app font and soft state fills. -->
<script lang="ts" setup>
import type { ToasterProps } from "vue-sonner"
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon, XIcon } from "@lucide/vue"
import { Toaster as Sonner } from "vue-sonner"
import "vue-sonner/style.css"
import { cn } from "../../utils"

const props = defineProps<ToasterProps>()
</script>

<template>
  <!-- The caller's props come first, so the clay options below are not reset by its unset ones. -->
  <Sonner
    v-bind="props"
    :class="cn('toaster group', props.class)"
    :style="{
      'fontFamily': 'var(--font-sans)',
      '--normal-bg': 'var(--popover)',
      '--normal-text': 'var(--popover-foreground)',
      '--normal-border': 'var(--border)',
      '--border-radius': 'var(--radius-card)',
      '--success-bg': 'var(--success-soft)',
      '--success-text': 'var(--success)',
      '--success-border': 'var(--success)',
      '--error-bg': 'var(--destructive-soft)',
      '--error-text': 'var(--destructive)',
      '--error-border': 'var(--destructive)',
      '--warning-bg': 'var(--warning-soft)',
      '--warning-text': 'var(--warning)',
      '--warning-border': 'var(--warning)',
    }"
    :toast-options="{ style: { borderWidth: 'var(--border-clay)', boxShadow: 'var(--shadow-clay)' } }"
    rich-colors
  >
    <template #success-icon>
      <CircleCheckIcon class="size-4" />
    </template>
    <template #info-icon>
      <InfoIcon class="size-4" />
    </template>
    <template #warning-icon>
      <TriangleAlertIcon class="size-4" />
    </template>
    <template #error-icon>
      <OctagonXIcon class="size-4" />
    </template>
    <template #loading-icon>
      <div>
        <Loader2Icon class="size-4 animate-spin" />
      </div>
    </template>
    <template #close-icon>
      <XIcon class="size-4" />
    </template>
  </Sonner>
</template>
