<!-- AI-ASSISTED: one labelled field of the join form, with its hint and its message linked by aria-describedby, keeping the caret when the parent rewrites the value. -->
<script setup lang="ts">
import { computed, useTemplateRef, watch } from 'vue'
import { Input } from '@/components/ui/input'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ id: string; label: string; hint?: string; error: string | null }>()
const model = defineModel<string>({ required: true })

const describedBy = computed(() =>
  [props.hint && `${props.id}-hint`, props.error !== null && `${props.id}-error`].filter(Boolean).join(' ') || undefined)
const input = useTemplateRef<{ $el: HTMLInputElement }>('input')
defineExpose({ focus: () => input.value?.$el.focus() })

/**
 * A parent that rewrites the typed value (the quiz ID upper-cases it) makes Vue set the input's value, which moves
 * the caret to the end. The selection seen at the input event is put back once the new value is in the DOM.
 */
let selection: [number | null, number | null] | null = null
function onInput(event: Event): void {
  const el = event.target as HTMLInputElement
  selection = [el.selectionStart, el.selectionEnd]
}
watch(model, () => {
  const el = input.value?.$el
  if (selection !== null && el !== undefined && document.activeElement === el) el.setSelectionRange(...selection)
  selection = null
}, { flush: 'post' })
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
      @input="onInput"
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
