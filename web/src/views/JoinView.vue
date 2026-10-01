<!-- AI-ASSISTED: the landing and join screen: quiz ID and name checks, the share link, the quiz preview and the join (UI spec §3.1). -->
<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import JoinField from '@/components/join/JoinField.vue'
import QuizPreviewCard from '@/components/join/QuizPreviewCard.vue'
import { fetchQuizPreview, type PreviewResult } from '@/components/join/preview'
import { displayNameError, normalizeQuizId, QUIZ_ID_MAX, quizIdError, readName, saveName } from '@/components/join/validation'
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
/** The last join failed for a reason other than the quiz ID: the form is open again, to retry. */
const joinFailed = ref(false)
let mounted = true
onBeforeUnmount(() => {
  mounted = false
})

const idField = useTemplateRef<{ focus: () => void }>('idField')
const nameField = useTemplateRef<{ focus: () => void }>('nameField')
const focus = (field: typeof idField) => void nextTick(() => field.value?.focus())

/** The latest lookup; `result` is null while it runs. Only the lookup of the current quiz ID is shown. */
const lookup = ref<{ quizId: string; promise: Promise<PreviewResult>; result: PreviewResult | null } | null>(null)
const shown = computed(() => (lookup.value?.quizId === quizId.value ? lookup.value : null))
const ended = computed(() => shown.value?.result?.kind === 'found' && shown.value.result.quiz.status === 'ended')

function loadPreview(id: string, again = false): Promise<PreviewResult> {
  if (lookup.value?.quizId === id && !again) return lookup.value.promise
  const promise = fetchQuizPreview(id)
  lookup.value = { quizId: id, promise, result: null }
  void promise.then((result) => {
    if (lookup.value?.promise !== promise) return
    lookup.value.result = result
    if (result.kind === 'not-found' && quizId.value === id) idError.value = strings.join.notFound
  })
  return promise
}

function onIdInput(value: string): void {
  quizId.value = normalizeQuizId(value)
  if (idError.value !== null) idError.value = quizIdError(quizId.value)
}

/** Trims and checks the quiz ID; true when it is well formed. */
function checkId(): boolean {
  quizId.value = quizId.value.trim()
  idError.value = quizIdError(quizId.value)
  return idError.value === null
}

function onIdBlur(): void {
  if (!checkId()) return
  void loadPreview(quizId.value)
  // Leaving the field again without an edit keeps the answer of the lookup already made.
  if (shown.value?.result?.kind === 'not-found') idError.value = strings.join.notFound
}

function onNameInput(value: string): void {
  if (nameError.value !== null) nameError.value = displayNameError(value)
}

function onNameBlur(): void {
  name.value = name.value.trim()
  nameError.value = displayNameError(name.value)
}

async function submit(): Promise<void> {
  if (joining.value) return
  joinFailed.value = false
  checkId()
  onNameBlur()
  if (idError.value !== null) return focus(idField)
  if (nameError.value !== null) return focus(nameField)
  joining.value = true
  const id = quizId.value
  // A miss or a failed lookup is asked again: the quiz may exist by now.
  const known = lookup.value?.quizId === id ? lookup.value.result : null
  const result = await loadPreview(id, known !== null && known.kind !== 'found')
  // The answer is stale once the screen has closed or the quiz ID has changed.
  if (!mounted || quizId.value !== id) {
    joining.value = false
    return
  }
  if (result.kind === 'not-found') {
    joining.value = false
    idError.value = strings.join.notFound
    return focus(idField)
  }
  saveName(name.value)
  try {
    store.join(id, name.value)
  } catch {
    // The client could not start, for example when storage is blocked.
    failJoin()
  }
}

function failJoin(): void {
  joining.value = false
  joinFailed.value = true
}

/**
 * How the join ended, or null while it runs (a `reconnecting` link may still join). Any other error reply to the
 * join, or a final close before `joined`, failed it: the client never sends that join again (protocol §1).
 */
const outcome = computed(() => {
  if (store.quiz !== null || store.ended) return 'ready'
  if (store.lastError?.code === 'QUIZ_NOT_FOUND') return 'not-found'
  return store.lastError?.requestType === 'join' || store.connection === 'closed' ? 'failed' : null
})

// The fields are read-only and links are ignored while joining, so `quizId` is still the ID that was sent.
watch(outcome, (result) => {
  if (!joining.value) return
  if (result === 'ready') void router.push({ name: 'quiz', params: { quizId: quizId.value } })
  else if (result === 'not-found') {
    joining.value = false
    idError.value = strings.join.notFound
    focus(idField)
  } else if (result === 'failed') failJoin()
})

// `/?quiz=VOCAB-42` (also the target of `/q/VOCAB-42`) fills the quiz ID and moves on to the name.
watch(
  () => route.query.quiz,
  (linked) => {
    if (joining.value) return
    if (typeof linked !== 'string' || linked.trim() === '') return focus(idField)
    quizId.value = normalizeQuizId(linked.trim())
    idError.value = quizIdError(quizId.value)
    if (idError.value !== null) return focus(idField)
    void loadPreview(quizId.value)
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

      <div
        aria-live="polite"
        class="empty:hidden"
      >
        <p
          v-if="shown !== null && shown.result === null"
          class="text-sm text-muted-foreground"
        >
          {{ strings.join.checking }}
        </p>
        <QuizPreviewCard
          v-else-if="shown?.result?.kind === 'found'"
          :quiz="shown.result.quiz"
        />
      </div>

      <JoinField
        id="display-name"
        ref="nameField"
        v-model="name"
        :label="strings.join.nameLabel"
        :error="nameError"
        :readonly="joining"
        autocomplete="nickname"
        @update:model-value="onNameInput"
        @blur="onNameBlur"
      />

      <p
        v-if="joinFailed"
        role="alert"
        class="text-sm text-destructive"
      >
        {{ strings.join.failed }}
      </p>

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
        {{ joining ? strings.join.joining : ended ? strings.join.submitEnded : strings.join.submit }}
      </Button>
    </form>
  </section>
</template>
