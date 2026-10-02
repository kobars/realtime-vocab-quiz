<!-- AI-ASSISTED: the type scale and the three weights, in the Clay font. -->
<script setup lang="ts">
import { themes } from '../../src/tokens'
import SpecimenItem from '../SpecimenItem.vue'

const SIZES = [
  { cls: 'text-sm', detail: '14 px' },
  { cls: 'text-base', detail: '16 px, the body and every input' },
  { cls: 'text-xl', detail: '20 px' },
  { cls: 'text-2xl', detail: '24 px' },
  { cls: 'text-title', detail: `--font-size-title (${themes.light['--font-size-title']})` },
  { cls: 'text-display', detail: `--font-size-display (${themes.light['--font-size-display']})` },
]
const WEIGHTS = [
  { cls: 'font-medium', detail: '500, body text' },
  { cls: 'font-bold', detail: '700, buttons' },
  { cls: 'font-extrabold', detail: '800, headings' },
]
</script>

<template>
  <p class="text-sm text-muted-foreground">
    {{ themes.light['--font-sans'] }}
  </p>
  <div class="flex flex-col gap-4">
    <SpecimenItem
      v-for="size in SIZES"
      :key="size.cls"
      :label="size.cls"
      :detail="size.detail"
    >
      <span
        :class="size.cls"
        class="leading-tight font-extrabold"
      >Vocabulary</span>
    </SpecimenItem>
  </div>
  <div class="flex flex-wrap gap-6">
    <SpecimenItem
      v-for="weight in WEIGHTS"
      :key="weight.cls"
      :label="weight.cls"
      :detail="weight.detail"
    >
      <span
        :class="weight.cls"
        class="text-xl"
      >Quiz</span>
    </SpecimenItem>
  </div>
  <SpecimenItem
    label="text-gradient"
    detail="--gradient-text, solid --primary where clipping is missing"
  >
    <span class="text-gradient text-title font-extrabold">Vocab Quiz</span>
  </SpecimenItem>
</template>
