<!-- AI-ASSISTED: one labelled field of the join form, with its hint and its message linked by aria-describedby. -->
<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { Input } from '@/components/ui/input'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ id: string; label: string; hint?: string; error: string | null }>()
const model = defineModel<string>({ required: true })

const describedBy = computed(() =>
  [props.hint && `${props.id}-hint`, props.error !== null && `${props.id}-error`].filter(Boolean).join(' ') || undefined)
const input = useTemplateRef<{ $el: HTMLInputElement }>('input')
defineExpose({ focus: () => input.value?.$el.focus() })
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label
      :for="id"
      class="text-sm font-medium"
    >{{ label }}</label>
    <Input
      :id
      ref="input"
      v-model="model"
      v-bind="$attrs"
      :aria-invalid="error === null ? undefined : 'true'"
      :aria-describedby="describedBy"
    />
    <p
      v-if="hint"
      :id="`${id}-hint`"
      class="text-sm text-muted-foreground"
    >
      {{ hint }}
    </p>
    <p
      v-if="error !== null"
      :id="`${id}-error`"
      class="text-sm text-destructive"
    >
      {{ error }}
    </p>
  </div>
</template>
