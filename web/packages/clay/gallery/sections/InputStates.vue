<!-- AI-ASSISTED: the input in each state, and one bound with v-model. -->
<script setup lang="ts">
import { ref } from 'vue'
import { Input } from '../../src'
import SpecimenItem from '../SpecimenItem.vue'

const name = ref('Ada')
const STATES = [
  { name: 'placeholder', value: '' },
  { name: 'filled', value: 'VOCAB-42' },
  { name: 'focus', value: 'VOCAB-42', preview: 'focus' },
  { name: 'invalid', value: 'VOCAB', invalid: true },
  { name: 'invalid, focus', value: 'VOCAB', invalid: true, preview: 'focus' },
  { name: 'disabled', value: 'VOCAB-42', disabled: true },
]
</script>

<template>
  <div class="grid gap-4 sm:grid-cols-2">
    <SpecimenItem
      v-for="state in STATES"
      :key="state.name"
      :label="state.name"
      class="w-full"
    >
      <Input
        :default-value="state.value"
        placeholder="Quiz ID"
        :aria-label="`Quiz ID, ${state.name}`"
        :aria-invalid="state.invalid ? 'true' : undefined"
        :data-preview="state.preview"
        :disabled="state.disabled"
      />
    </SpecimenItem>
  </div>
  <SpecimenItem
    label="v-model"
    :detail="`Bound value: ${name}`"
    class="w-full"
  >
    <Input
      v-model="name"
      aria-label="Display name"
    />
  </SpecimenItem>
</template>
