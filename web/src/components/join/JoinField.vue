<!-- AI-ASSISTED: one labelled field of the join form, with its hint and its message (with a decorative alert icon) linked by aria-describedby, keeping the caret when the parent rewrites the value, and kept out of password managers. -->
<script setup lang="ts">
import { CircleAlert } from '@lucide/vue'
import { computed, useTemplateRef, watch } from 'vue'
import { Input } from '@quiz/clay'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ id: string; label: string; hint?: string; error: string | null }>()
const model = defineModel<string>({ required: true })

const describedBy = computed(() =>
  [props.hint && `${props.id}-hint`, props.error !== null && `${props.id}-error`].filter(Boolean).join(' ') || undefined)
const input = useTemplateRef<{ $el: HTMLInputElement }>('input')
defineExpose({ focus: () => input.value?.$el.focus() })

/**
 * A parent that rewrites the typed value (the quiz ID upper-cases it) makes Vue set the input's value, which moves
 * the caret to the end. The selection is read when the new value arrives, before the DOM has it, and put back after.
 * Reading it in an input listener instead fails in browsers: Vue flushes between the input listeners, so a listener
 * that runs after v-model's sees the caret that the restore has already moved.
 */
let selection: [number | null, number | null] | null = null
const focusedInput = (): HTMLInputElement | null => {
  const el = input.value?.$el
  return el !== undefined && document.activeElement === el ? el : null
}
watch(model, () => {
  const el = focusedInput()
  selection = el === null ? null : [el.selectionStart, el.selectionEnd]
}, { flush: 'pre' })
watch(model, () => {
  if (selection !== null) focusedInput()?.setSelectionRange(...selection)
  selection = null
}, { flush: 'post' })
</script>

<template>
  <!-- Neither field is a login: the data- attributes keep 1Password, LastPass, Bitwarden and Dashlane from offering to fill it, which autocomplete alone does not. -->
  <div class="flex flex-col gap-2">
    <label
      :for="id"
      class="font-semibold"
    >{{ label }}</label>
    <Input
      :id
      ref="input"
      v-model="model"
      v-bind="$attrs"
      :aria-invalid="error === null ? undefined : 'true'"
      :aria-describedby="describedBy"
      data-1p-ignore
      data-lpignore="true"
      data-bwignore
      data-form-type="other"
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
      class="flex items-center gap-1.5 text-sm text-destructive"
    >
      <CircleAlert
        class="size-4 shrink-0"
        aria-hidden="true"
      />
      {{ error }}
    </p>
  </div>
</template>
