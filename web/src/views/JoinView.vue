<!-- AI-ASSISTED: the landing and join screen: quiz ID and name checks, the share link, the quiz preview (a miss also announced) and the join (with the busy retry, the blocking card and the rejoin after a reload), a link back to the quiz this tab is still in, a quiet "Host a quiz" link when the server offers hosting, in a clay card over the hero decoration (UI spec §3.1). -->
<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchBanks } from '@/components/host/hosting'
import JoinField from '@/components/join/JoinField.vue'
import QuizPreviewCard from '@/components/join/QuizPreviewCard.vue'
import { fetchQuizPreview, type PreviewResult } from '@/components/join/preview'
import { displayNameError, normalizeQuizId, QUIZ_ID_MAX, quizIdError, readName, saveName } from '@/components/join/validation'
import ErrorMessage from '@/components/status/ErrorMessage.vue'
import { Button, Card } from '@quiz/clay'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const route = useRoute()
const router = useRouter()
const store = useQuizStore()

/**
 * The router joined again after a reload of the quiz screen, before this lazily loaded screen opened: the join may
 * already have ended, so the outcome watcher below runs at once.
 */
const resuming = store.takeResume()
const quizId = ref(resuming ? (store.quizId ?? '') : '')
const name = ref(readName())
const idError = ref<string | null>(null)
const nameError = ref<string | null>(null)
const joining = ref(resuming)
/** The last join failed for a reason other than the quiz ID: the form is open again, to retry. */
const joinFailed = ref(false)
/** The last join ended in a blocked state (UI spec §3.7): its card says what to do instead of "try again". */
const joinBlocked = ref(false)
/** The client sends a join that got `UNAVAILABLE` again after the backoff: the spinner stays and says so. */
const busy = computed(() => joining.value && store.busy !== null)
/** The quiz this tab is still in, after the wordmark led here from its screen. */
const live = computed(() => (!joining.value && store.blocked === null && (store.quiz !== null || store.ended) ? store.quizId : null))
let mounted = true
onBeforeUnmount(() => {
  mounted = false
})
/** The host link shows only once the server lists question sets to host (a 404 means hosting is off). */
const hostable = ref(false)
void fetchBanks().then((result) => {
  if (mounted) hostable.value = result.kind === 'ok'
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

/**
 * A field left empty is flagged by the submit, not on blur: a message added on blur would push down what the
 * pointer is pressing (the "Host a quiz" link) between mousedown and mouseup, and the click would be lost.
 */
const leftEmpty = (value: string, error: string | null) => value.trim() === '' && error === null

function onIdBlur(): void {
  if (leftEmpty(quizId.value, idError.value)) return
  if (!checkId()) return
  void loadPreview(quizId.value)
  // Leaving the field again without an edit keeps the answer of the lookup already made.
  if (shown.value?.result?.kind === 'not-found') idError.value = strings.join.notFound
}

function onNameInput(value: string): void {
  if (nameError.value !== null) nameError.value = displayNameError(value)
}

function onNameBlur(): void {
  if (leftEmpty(name.value, nameError.value)) return
  checkName()
}

function checkName(): void {
  name.value = name.value.trim()
  nameError.value = displayNameError(name.value)
}

async function submit(): Promise<void> {
  if (joining.value) return
  joinFailed.value = false
  checkId()
  checkName()
  if (idError.value !== null) return focus(idField)
  if (nameError.value !== null) return focus(nameField)
  joining.value = true
  joinBlocked.value = false
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
 * How the join ended, or null while it runs (a `reconnecting` link or a busy server may still join). A blocked state
 * has its own card. Any other error reply to the join returns the store to `idle`, and a final close before `joined`
 * leaves it `closed`: the client never sends that join again (protocol §1).
 */
const outcome = computed(() => {
  if (store.quiz !== null || store.ended) return 'ready'
  if (store.lastError?.code === 'QUIZ_NOT_FOUND') return 'not-found'
  if (store.blocked !== null) return 'blocked'
  return store.connection === 'idle' || store.connection === 'closed' ? 'failed' : null
})

// The fields are read-only and links are ignored while joining, so `quizId` is still the ID that was sent.
watch(outcome, (result, before) => {
  // "Try again" or "Use this tab" on the blocking card joins the last quiz again from this screen, even after an edit.
  if (before === 'blocked' && result === null) {
    joining.value = true
    joinBlocked.value = false
    quizId.value = store.quizId ?? quizId.value
    idError.value = null
  }
  if (!joining.value) return
  if (result === 'ready') void router.push({ name: 'quiz', params: { quizId: store.quizId ?? quizId.value } })
  else if (result === 'not-found') {
    joining.value = false
    idError.value = strings.join.notFound
    focus(idField)
  } else if (result === 'failed') failJoin()
  else if (result === 'blocked') {
    joining.value = false
    joinBlocked.value = true
  }
}, { immediate: true })

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
  <section
    data-test="hero"
    class="hero-blobs mx-auto flex w-full max-w-110 flex-col gap-6"
  >
    <h1 class="text-title sm:text-display">
      {{ strings.join.title }}
    </h1>
    <Button
      v-if="live !== null"
      as-child
      variant="outline"
      class="self-start"
    >
      <RouterLink
        :to="{ name: 'quiz', params: { quizId: live } }"
        data-test="resume"
      >
        {{ strings.join.resume(live) }}
      </RouterLink>
    </Button>
    <ErrorMessage v-if="joinBlocked && store.blocked !== null" />
    <Card>
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

        <!-- A miss shows under the quiz ID field; here it is only announced, as the lookup may end after the focus left. -->
        <div
          aria-live="polite"
          data-test="preview-status"
          :class="shown?.result?.kind === 'not-found' ? 'sr-only' : 'empty:hidden'"
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
          <p v-else-if="shown?.result?.kind === 'not-found'">
            {{ strings.join.notFound }}
          </p>
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
        <!-- The live region stays in the page, so the busy text is announced when it appears. -->
        <p
          role="status"
          data-test="join-status"
          :class="busy ? 'text-sm text-muted-foreground' : 'sr-only'"
        >
          {{ busy ? strings.connection.busy : '' }}
        </p>

        <Button
          type="submit"
          size="lg"
          class="w-full sm:w-auto sm:self-start"
          :disabled="joining"
        >
          <LoaderCircle
            v-if="joining"
            class="motion-safe:animate-spin"
            aria-hidden="true"
          />
          {{ joining ? strings.join.joining : ended ? strings.join.submitEnded : strings.join.submit }}
        </Button>
      </form>
    </Card>
    <p
      v-if="hostable"
      data-test="host-entry"
      class="flex flex-wrap items-center gap-x-2 text-muted-foreground"
    >
      {{ strings.join.hostPrompt }}
      <Button
        as-child
        variant="link"
        class="px-0"
      >
        <RouterLink :to="{ name: 'host' }">
          {{ strings.join.host }}
        </RouterLink>
      </Button>
    </p>
  </section>
</template>
