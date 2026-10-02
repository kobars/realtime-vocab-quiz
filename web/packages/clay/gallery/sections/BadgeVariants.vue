<!-- AI-ASSISTED: every badge variant, and a badge with a leading icon. -->
<script setup lang="ts">
import { RadioIcon } from '@lucide/vue'
import { Badge, type BadgeVariants } from '../../src'

type Variant = NonNullable<BadgeVariants['variant']>
const VARIANTS: Variant[] = ['default', 'secondary', 'outline', 'mint', 'cyan', 'sun', 'success', 'destructive', 'warning']
</script>

<template>
  <div class="flex flex-wrap gap-3">
    <Badge
      v-for="variant in VARIANTS"
      :key="variant"
      :variant="variant"
    >
      {{ variant }}
    </Badge>
  </div>
  <div class="flex flex-wrap gap-3">
    <Badge variant="success">
      <template #icon>
        <RadioIcon aria-hidden="true" />
      </template>
      Live
    </Badge>
  </div>
</template>
