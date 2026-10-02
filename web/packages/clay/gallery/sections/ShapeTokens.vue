<!-- AI-ASSISTED: the radii, outline widths, shadows and the primary gradient. -->
<script setup lang="ts">
import { themes } from '../../src/tokens'
import SpecimenItem from '../SpecimenItem.vue'

const radius = themes.light['--radius']
const RADII = [
  { cls: 'rounded-sm', detail: '--radius − 4 px' },
  { cls: 'rounded-md', detail: '--radius − 2 px' },
  { cls: 'rounded-lg', detail: `--radius (${radius})` },
  { cls: 'rounded-xl', detail: '--radius + 4 px' },
  { cls: 'rounded-card', detail: `--radius-card (${themes.light['--radius-card']})` },
  { cls: 'rounded-full', detail: 'pills' },
]
const BORDERS = [
  { cls: 'border-clay', detail: `--border-clay (${themes.light['--border-clay']}): cards, buttons, inputs` },
  { cls: 'border-2', detail: '2 px: badges, the progress track' },
]
// Whole class names, so Tailwind finds them in this file.
const SHADOWS = ['shadow-clay', 'shadow-clay-lift', 'shadow-press', 'shadow-press-hover', 'shadow-press-active', 'shadow-inset'].map(
  (cls) => ({ cls, detail: `--${cls}` }),
)
</script>

<template>
  <h4 class="font-bold">
    Radii
  </h4>
  <ul class="grid grid-cols-2 gap-4 sm:grid-cols-3">
    <li
      v-for="item in RADII"
      :key="item.cls"
    >
      <SpecimenItem
        :label="item.cls"
        :detail="item.detail"
      >
        <div
          :class="item.cls"
          class="h-14 w-full border-clay border-input bg-card"
        />
      </SpecimenItem>
    </li>
  </ul>
  <h4 class="font-bold">
    Outlines
  </h4>
  <ul class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <li
      v-for="item in BORDERS"
      :key="item.cls"
    >
      <SpecimenItem
        :label="item.cls"
        :detail="item.detail"
      >
        <div
          :class="item.cls"
          class="h-14 w-full rounded-lg border-input bg-card"
        />
      </SpecimenItem>
    </li>
  </ul>
  <h4 class="font-bold">
    Shadows
  </h4>
  <ul class="grid grid-cols-2 gap-6 sm:grid-cols-3">
    <li
      v-for="item in SHADOWS"
      :key="item.cls"
    >
      <SpecimenItem
        :label="item.cls"
        :detail="item.detail"
      >
        <div
          :class="item.cls"
          class="h-16 w-full rounded-lg border-clay border-border bg-card"
        />
      </SpecimenItem>
    </li>
  </ul>
  <h4 class="font-bold">
    Gradient
  </h4>
  <SpecimenItem
    label="bg-gradient-primary"
    detail="--gradient-primary: the primary button, the progress fill"
  >
    <div class="h-14 w-full rounded-lg bg-gradient-primary" />
  </SpecimenItem>
</template>
