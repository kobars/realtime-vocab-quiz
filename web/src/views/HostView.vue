<!-- AI-ASSISTED: the host screen at /host: pick a question set to create a public quiz, then the host panel; the rate-limited, full, off, ended and network states; the hosted quiz survives a refresh of the tab (UI spec §3.8). -->
<script setup lang="ts">
import { BookOpenText, ChevronRight, LoaderCircle } from '@lucide/vue'
import { nextTick, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import HostPanel from '@/components/host/HostPanel.vue'
import {
  type Bank,
  type BanksResult,
  clearHostedQuiz,
  createQuiz,
  fetchBanks,
  type HostedQuiz,
  readHostedQuiz,
  saveHostedQuiz,
} from '@/components/host/hosting'
import { Badge, Button, Card } from '@quiz/clay'
import { strings } from '@/strings'

const hosted = ref<HostedQuiz | null>(readHostedQuiz())
/** The quiz this tab hosted until it ended; its card offers the results and another quiz. */
const ended = ref<HostedQuiz | null>(null)
/** null while the list loads. */
const banks = ref<BanksResult | null>(null)
/** The bank being created from. */
const creating = ref<string | null>(null)
/** Why the last create failed; while `waiting`, a 429 keeps the sets locked until its Retry-After has passed. */
const notice = ref<string | null>(null)
const waiting = ref(false)
let waitTimer: ReturnType<typeof setTimeout> | undefined
let mounted = true
onBeforeUnmount(() => {
  mounted = false
  clearTimeout(waitTimer)
})

const endedHeading = useTemplateRef<HTMLElement>('endedHeading')

async function loadBanks(): Promise<void> {
  banks.value = null
  const result = await fetchBanks()
  if (mounted) banks.value = result
}
if (hosted.value === null) void loadBanks()

const waitText = (seconds: number) =>
  seconds < 60 ? strings.host.seconds(seconds) : strings.host.minutes(Math.ceil(seconds / 60))

async function create(bank: Bank): Promise<void> {
  if (creating.value !== null || waiting.value) return
  creating.value = bank.id
  notice.value = null
  const result = await createQuiz(bank.id)
  creating.value = null
  // Saved even after the visitor has left the page, so /host shows the quiz and its host token again.
  if (result.kind === 'created') saveHostedQuiz(result.quiz)
  if (!mounted) return
  switch (result.kind) {
    case 'created':
      hosted.value = result.quiz
      return
    case 'rate-limited':
      notice.value = strings.host.rateLimited(waitText(result.retryAfterS))
      waiting.value = true
      waitTimer = setTimeout(() => {
        waiting.value = false
        notice.value = null
      }, result.retryAfterS * 1_000)
      return
    case 'full':
      notice.value = strings.host.full
      return
    case 'off':
      banks.value = { kind: 'off' }
      return
    case 'invalid':
      notice.value = strings.host.invalid
      return void loadBanks()
    case 'error':
      notice.value = strings.host.error
  }
}

function onEnded(): void {
  ended.value = hosted.value
  hosted.value = null
  clearHostedQuiz()
  void nextTick(() => endedHeading.value?.focus())
}

function hostAnother(): void {
  ended.value = null
  void loadBanks()
}
</script>

<template>
  <section class="mx-auto flex w-full max-w-200 flex-col gap-6">
    <div class="flex flex-col gap-2">
      <h1 class="text-title sm:text-display">
        {{ strings.host.title }}
      </h1>
      <p
        v-if="hosted === null && ended === null"
        class="text-muted-foreground"
      >
        {{ strings.host.intro }}
      </p>
    </div>

    <HostPanel
      v-if="hosted !== null"
      :quiz="hosted"
      @ended="onEnded"
    />

    <Card
      v-else-if="ended !== null"
      data-test="host-ended"
      class="items-start gap-4"
    >
      <h2
        ref="endedHeading"
        tabindex="-1"
        class="text-2xl"
      >
        {{ strings.host.ended(ended.quizId) }}
      </h2>
      <p class="text-muted-foreground">
        {{ strings.host.endedBody }}
      </p>
      <div class="flex flex-col gap-3 self-stretch sm:flex-row sm:self-start">
        <Button @click="hostAnother">
          {{ strings.host.again }}
        </Button>
        <Button
          as-child
          variant="outline"
        >
          <RouterLink :to="ended.sharePath">
            {{ strings.host.openLink }}
          </RouterLink>
        </Button>
      </div>
    </Card>

    <template v-else>
      <!-- Always in the page, so a failed create is announced when it appears. -->
      <p
        role="status"
        data-test="host-notice"
        :class="notice === null ? 'sr-only' : 'rounded-card border-clay border-warning/40 bg-warning-soft p-4 font-semibold text-warning'"
      >
        {{ notice ?? '' }}
      </p>

      <p
        v-if="banks === null"
        role="status"
        class="flex items-center gap-2 text-muted-foreground"
      >
        <LoaderCircle
          class="size-5 motion-safe:animate-spin"
          aria-hidden="true"
        />
        {{ strings.host.loading }}
      </p>

      <Card
        v-else-if="banks.kind !== 'ok'"
        data-test="host-unavailable"
        class="items-start gap-4"
      >
        <p class="text-lg font-bold">
          {{ banks.kind === 'off' ? strings.host.off : strings.host.error }}
        </p>
        <Button
          v-if="banks.kind === 'error'"
          @click="loadBanks"
        >
          {{ strings.host.retry }}
        </Button>
        <Button
          v-else
          as-child
          variant="outline"
        >
          <RouterLink to="/">
            {{ strings.notFound.home }}
          </RouterLink>
        </Button>
      </Card>

      <ul
        v-else
        :aria-label="strings.host.banksLabel"
        class="grid gap-4 sm:grid-cols-2"
      >
        <li
          v-for="bank in banks.banks"
          :key="bank.id"
        >
          <button
            type="button"
            :data-bank="bank.id"
            :aria-disabled="creating !== null || waiting ? 'true' : undefined"
            class="flex min-h-24 w-full items-center gap-4 rounded-card border-clay border-input bg-card p-4 text-left shadow-press transition-[border-color,box-shadow,translate] duration-fast ease-spring focus-hug not-aria-disabled:hover:shadow-press-hover not-aria-disabled:active:shadow-press-active motion-safe:not-aria-disabled:hover:-translate-y-0.5 motion-safe:not-aria-disabled:active:translate-y-0.5 aria-disabled:cursor-not-allowed"
            :class="creating !== null && creating !== bank.id && 'opacity-60'"
            @click="create(bank)"
          >
            <span
              class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-cyan text-night"
              aria-hidden="true"
            >
              <BookOpenText class="size-6" />
            </span>
            <span class="flex min-w-0 flex-1 flex-col items-start gap-2">
              <span class="text-lg font-extrabold">{{ bank.title }}</span>
              <Badge variant="secondary">{{ strings.host.questions(bank.questionCount) }}</Badge>
            </span>
            <span class="flex shrink-0 items-center gap-1 font-bold text-primary">
              <LoaderCircle
                v-if="creating === bank.id"
                class="size-4 motion-safe:animate-spin"
                aria-hidden="true"
              />
              {{ creating === bank.id ? strings.host.creating : strings.host.pick }}
              <ChevronRight
                v-if="creating !== bank.id"
                class="size-5"
                aria-hidden="true"
              />
            </span>
          </button>
        </li>
      </ul>
    </template>
  </section>
</template>
