<!-- AI-ASSISTED: every colour token of a theme as a swatch, with its value and its contrast on the page and on a card. -->
<script setup lang="ts">
import { computed } from 'vue'
import { contrast, themes } from '../../src/tokens'
import SpecimenItem from '../SpecimenItem.vue'
import { colourTokens, ratio, type Theme } from '../theme'

const props = defineProps<{ theme: Theme }>()
const swatches = computed(() => {
  const { '--background': page = '', '--card': card = '' } = themes[props.theme]
  return colourTokens(props.theme).map(([name, value]) => ({
    name,
    detail: `${value} · ${ratio(contrast(value, page))} on page · ${ratio(contrast(value, card))} on card`,
  }))
})
</script>

<template>
  <ul class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <li
      v-for="swatch in swatches"
      :key="swatch.name"
    >
      <SpecimenItem
        :label="swatch.name"
        :detail="swatch.detail"
      >
        <div
          class="h-12 w-full rounded-lg border-2 border-border"
          :style="{ background: `var(${swatch.name})` }"
        />
      </SpecimenItem>
    </li>
  </ul>
</template>
