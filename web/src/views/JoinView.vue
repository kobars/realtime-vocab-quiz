<!-- AI-ASSISTED: the landing and join screen: quiz ID and name checks, the share link and the join (UI spec §3.1). -->
<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { nextTick, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import JoinField from '@/components/join/JoinField.vue'
import { displayNameError, NAME_MAX, normalizeQuizId, QUIZ_ID_MAX, quizIdError, readName, saveName } from '@/components/join/validation'
import { Button } from '@/components/ui/button'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const route = useRoute()
const router = useRouter()
const store = useQuizStore()

const quizId = ref('')
const name = ref(readName())
const idError = ref<string | null>(null)
const nameError = ref<string | null>(null)
const joining = ref(false)

const idField = useTemplateRef<{ focus: () => void }>('idField')
const nameField = useTemplateRef<{ focus: () => void }>('nameField')
const focus = (field: typeof idField) => void nextTick(() => field.value?.focus())

function onIdInput(value: string): void {
  quizId.value = normalizeQuizId(value)
  if (idError.value !== null) idError.value = quizIdError(quizId.value)
}

function onIdBlur(): void {
  quizId.value = quizId.value.trim()
  idError.value = quizIdError(quizId.value)
}

function onNameInput(value: string): void {
  if (nameError.value !== null) nameError.value = displayNameError(value)
}

function onNameBlur(): void {
  name.value = name.value.trim()
  nameError.value = displayNameError(name.value)
}

function submit(): void {
  if (joining.value) return
  onIdBlur()
  onNameBlur()
  if (idError.value !== null) return focus(idField)
  if (nameError.value !== null) return focus(nameField)
  joining.value = true
  saveName(name.value)
  store.join(quizId.value, name.value)
}

// The fields are read-only while joining, so `quizId` is still the ID that was sent.
watch([() => store.quiz !== null || store.ended, () => store.lastError?.code], ([ready, code]) => {
  if (!joining.value) return
  if (ready) void router.push({ name: 'quiz', params: { quizId: quizId.value } })
  else if (code === 'QUIZ_NOT_FOUND') {
    joining.value = false
    idError.value = strings.join.notFound
    focus(idField)
  }
})

// `/?quiz=VOCAB-42` (also the target of `/q/VOCAB-42`) fills the quiz ID and moves on to the name.
watch(
  () => route.query.quiz,
  (linked) => {
    if (typeof linked !== 'string' || linked.trim() === '') return focus(idField)
    quizId.value = normalizeQuizId(linked.trim())
    idError.value = quizIdError(quizId.value)
    if (idError.value !== null) return focus(idField)
    focus(nameField)
  },
  { immediate: true },
)
</script>

<template>
  <section class="mx-auto flex w-full max-w-md flex-col gap-6">
    <h1 class="text-2xl font-semibold">
      {{ strings.join.title }}
    </h1>
    <form
      class="flex flex-col gap-5"
      novalidate
      @submit.prevent="submit"
    >
      <JoinField
        id="quiz-id"
        ref="idField"
        :model-value="quizId"
        :label="strings.join.quizIdLabel"
        :hint="strings.join.quizIdHint"
        :error="idError"
        :maxlength="QUIZ_ID_MAX"
        :readonly="joining"
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        @update:model-value="onIdInput"
        @blur="onIdBlur"
      />

      <JoinField
        id="display-name"
        ref="nameField"
        v-model="name"
        :label="strings.join.nameLabel"
        :error="nameError"
        :maxlength="NAME_MAX"
        :readonly="joining"
        autocomplete="nickname"
        @update:model-value="onNameInput"
        @blur="onNameBlur"
      />

      <Button
        type="submit"
        class="h-11"
        :disabled="joining"
      >
        <LoaderCircle
          v-if="joining"
          class="animate-spin"
          aria-hidden="true"
        />
        {{ joining ? strings.join.joining : strings.join.submit }}
      </Button>
    </form>
  </section>
</template>
