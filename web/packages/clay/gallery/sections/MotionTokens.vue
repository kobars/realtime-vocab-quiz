<!-- AI-ASSISTED: the duration and easing tokens; each bar is as long as its duration, and reduced motion sets all of them to 0 ms. -->
<script setup lang="ts">
import { themes } from '../../src/tokens'
import SpecimenItem from '../SpecimenItem.vue'

const DURATIONS = ['--motion-fast', '--motion-base', '--motion-slow', '--motion-pop', '--motion-count', '--stagger'].map((name) => ({
  name,
  ms: Number.parseInt(themes.light[name] ?? '0', 10),
}))
const longest = Math.max(...DURATIONS.map((duration) => duration.ms))
const EASINGS = ['--ease-standard', '--ease-spring'].map((name) => ({ name, value: themes.light[name] ?? '' }))
</script>

<template>
  <ul class="flex flex-col gap-4">
    <li
      v-for="duration in DURATIONS"
      :key="duration.name"
    >
      <SpecimenItem
        :label="duration.name"
        :detail="`${duration.ms} ms`"
      >
        <div
          class="h-3 rounded-full bg-gradient-primary"
          :style="{ width: `${(duration.ms / longest) * 100}%` }"
        />
      </SpecimenItem>
    </li>
  </ul>
  <ul class="flex flex-col gap-3">
    <li
      v-for="easing in EASINGS"
      :key="easing.name"
    >
      <SpecimenItem
        :label="easing.name"
        :detail="easing.value"
      />
    </li>
  </ul>
</template>
