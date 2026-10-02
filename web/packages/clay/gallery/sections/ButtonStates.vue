<!-- AI-ASSISTED: every button variant in every state, every size, and a button with a leading icon. -->
<script setup lang="ts">
import { ArrowRightIcon, PlusIcon } from '@lucide/vue'
import { Button, type ButtonVariants } from '../../src'
import SpecimenItem from '../SpecimenItem.vue'
import { STATES } from './states'

type Variant = NonNullable<ButtonVariants['variant']>
type Size = NonNullable<ButtonVariants['size']>
const VARIANTS: Variant[] = ['default', 'secondary', 'outline', 'ghost', 'link', 'destructive', 'mint']
const SIZES: Size[] = ['sm', 'default', 'lg']
const ICON_SIZES: Size[] = ['icon', 'icon-lg']
</script>

<template>
  <div
    v-for="variant in VARIANTS"
    :key="variant"
    class="flex flex-col gap-3"
  >
    <h4 class="font-bold">
      {{ variant }}
    </h4>
    <div class="flex flex-wrap gap-4">
      <SpecimenItem
        v-for="state in STATES"
        :key="state.name"
        :label="state.name"
      >
        <Button
          :variant="variant"
          :data-preview="state.preview"
          :disabled="state.disabled"
        >
          Start
        </Button>
      </SpecimenItem>
    </div>
  </div>
  <h4 class="font-bold">
    Sizes
  </h4>
  <div class="flex flex-wrap items-end gap-4">
    <SpecimenItem
      v-for="size in SIZES"
      :key="size"
      :label="size"
    >
      <Button :size="size">
        Start
      </Button>
    </SpecimenItem>
    <SpecimenItem
      v-for="size in ICON_SIZES"
      :key="size"
      :label="size"
    >
      <Button
        :size="size"
        variant="outline"
        aria-label="Add"
      >
        <PlusIcon />
      </Button>
    </SpecimenItem>
    <SpecimenItem label="with icon">
      <Button>
        Next <ArrowRightIcon />
      </Button>
    </SpecimenItem>
  </div>
</template>
