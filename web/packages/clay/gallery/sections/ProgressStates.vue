<!-- AI-ASSISTED: the progress bar empty, part-filled against max and full. -->
<script setup lang="ts">
import { Progress } from '../../src'
import SpecimenItem from '../SpecimenItem.vue'

const VALUES = [0, 3, 10]
</script>

<template>
  <SpecimenItem
    v-for="value in VALUES"
    :key="value"
    :label="`${value} of 10`"
    class="w-full"
  >
    <Progress
      :model-value="value"
      :max="10"
      :aria-label="`Question ${value} of 10`"
    />
  </SpecimenItem>
</template>
