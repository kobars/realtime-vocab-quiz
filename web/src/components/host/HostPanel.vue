<!-- AI-ASSISTED: the host's controls for an open quiz: the quiz ID, the player link with a copy button and its QR code, the live player count (polled while the page is visible), a link to join as a player and "End quiz" with a confirm step (UI spec §3.8). -->
<script setup lang="ts">
import { Copy, ExternalLink, LoaderCircle, Users } from '@lucide/vue'
import { useDocumentVisibility, useIntervalFn } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import QrCode from '@/components/host/QrCode.vue'
import { endQuiz, type HostedQuiz, POLL_MS } from '@/components/host/hosting'
import { fetchQuizPreview } from '@/components/join/preview'
import { Badge, Button, Card, Input } from '@quiz/clay'
import { strings } from '@/strings'

/** How long "Link copied" stays. */
const COPIED_MS = 4_000

const props = defineProps<{ quiz: HostedQuiz }>()
const emit = defineEmits<{ ended: [] }>()

const shareUrl = computed(() => new URL(props.quiz.sharePath, window.location.origin).href)
const closesAt = computed(() => new Date(props.quiz.endsAtMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
const players = ref<number | null>(null)
const copyStatus = ref<'copied' | 'failed' | null>(null)
const confirming = ref(false)
const ending = ref(false)
const endError = ref<string | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | undefined
let mounted = true

const heading = useTemplateRef<HTMLElement>('heading')
const endButton = useTemplateRef<{ $el: HTMLElement }>('endButton')
const keepButton = useTemplateRef<{ $el: HTMLElement }>('keepButton')

/** The quiz has ended or is gone once its window closes, an admin ends it, or another tab ends it. */
async function poll(): Promise<void> {
  const result = await fetchQuizPreview(props.quiz.quizId)
  if (!mounted) return
  if (result.kind === 'found') players.value = result.quiz.players
  if (result.kind === 'not-found' || (result.kind === 'found' && result.quiz.status === 'ended')) emit('ended')
}

const visibility = useDocumentVisibility()
// Resuming reads at once, so a tab that comes back into view shows the current count.
const polling = useIntervalFn(() => void poll(), POLL_MS, { immediate: false, immediateCallback: true })
watch(visibility, (state) => (state === 'visible' ? polling.resume() : polling.pause()), { immediate: true })
onMounted(() => heading.value?.focus())
onBeforeUnmount(() => {
  mounted = false
  clearTimeout(copyTimer)
})

async function copy(): Promise<void> {
  clearTimeout(copyTimer)
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    copyStatus.value = 'copied'
  } catch {
    copyStatus.value = 'failed'
  }
  copyTimer = setTimeout(() => (copyStatus.value = null), COPIED_MS)
}

function askToEnd(): void {
  confirming.value = true
  endError.value = null
  void nextTick(() => keepButton.value?.$el.focus())
}

/** Once "End it now" is sent, the end goes through, so "Keep it open" no longer offers to cancel it. */
function keepOpen(): void {
  if (ending.value) return
  confirming.value = false
  void nextTick(() => endButton.value?.$el.focus())
}

async function end(): Promise<void> {
  if (ending.value) return
  ending.value = true
  const result = await endQuiz(props.quiz)
  ending.value = false
  if (result.kind === 'ended' || result.kind === 'gone') return emit('ended')
  endError.value = result.kind === 'forbidden' ? strings.host.forbidden : strings.host.endFailed
}
</script>

<template>
  <Card data-test="host-panel">
    <div class="flex flex-col gap-6 md:flex-row md:items-start">
      <div class="flex min-w-0 flex-1 flex-col gap-5">
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="mint">
            {{ strings.join.preview.open }}
          </Badge>
          <span class="text-sm text-muted-foreground">{{ strings.host.closesAt(closesAt) }}</span>
        </div>
        <h2
          ref="heading"
          tabindex="-1"
          class="text-2xl"
        >
          {{ strings.host.ready }}
        </h2>
        <div class="flex flex-col gap-1">
          <p class="text-sm font-semibold text-muted-foreground">
            {{ strings.host.quizIdLabel }}
          </p>
          <p
            data-test="host-quiz-id"
            class="text-2xl font-extrabold tracking-wide break-all text-primary sm:text-display"
          >
            {{ quiz.quizId }}
          </p>
        </div>
        <div class="flex flex-col gap-2">
          <label
            for="share-link"
            class="font-semibold"
          >{{ strings.host.linkLabel }}</label>
          <div class="flex flex-col gap-3 sm:flex-row">
            <Input
              id="share-link"
              :model-value="shareUrl"
              readonly
              @focus="($event.target as HTMLInputElement).select()"
            />
            <Button
              variant="outline"
              data-test="copy"
              @click="copy"
            >
              <Copy aria-hidden="true" />
              {{ strings.host.copy }}
            </Button>
          </div>
          <p
            role="status"
            data-test="copy-status"
            :class="copyStatus === 'failed' ? 'text-sm text-destructive' : 'text-sm text-success empty:hidden'"
          >
            {{ copyStatus === 'copied' ? strings.host.copied : copyStatus === 'failed' ? strings.host.copyFailed : '' }}
          </p>
        </div>
        <p
          aria-live="polite"
          aria-atomic="true"
          data-test="players"
          class="flex min-h-7 items-center gap-2 text-lg font-bold tabular-nums"
        >
          <Users
            class="size-5 text-primary"
            aria-hidden="true"
          />
          {{ players === null ? '' : strings.host.players(players) }}
        </p>
      </div>
      <QrCode
        :value="shareUrl"
        :label="strings.host.qrLabel(shareUrl)"
        class="mx-auto w-full max-w-56 shrink-0 md:mx-0 md:w-56"
      />
    </div>
    <div class="flex flex-col gap-3 border-t-2 border-border pt-6 sm:flex-row sm:flex-wrap sm:items-center">
      <Button
        as-child
        variant="outline"
      >
        <a
          :href="shareUrl"
          target="_blank"
          rel="noopener"
          data-test="join-as-player"
        >
          {{ strings.host.joinAsPlayer }}
          <ExternalLink aria-hidden="true" />
          <span class="sr-only">{{ strings.host.newTab }}</span>
        </a>
      </Button>
      <Button
        v-if="!confirming"
        ref="endButton"
        variant="destructive"
        class="sm:ml-auto"
        data-test="end"
        @click="askToEnd"
      >
        {{ strings.host.end }}
      </Button>
    </div>
    <div
      v-if="confirming"
      data-test="confirm-end"
      class="flex flex-col gap-4 rounded-card border-clay border-destructive/40 bg-destructive-soft p-4"
    >
      <p class="font-semibold">
        {{ strings.host.confirmEnd }}
      </p>
      <div class="flex flex-col gap-3 sm:flex-row">
        <Button
          variant="destructive"
          data-test="confirm"
          :aria-busy="ending"
          @click="end"
        >
          <LoaderCircle
            v-if="ending"
            class="motion-safe:animate-spin"
            aria-hidden="true"
          />
          {{ ending ? strings.host.ending : strings.host.confirm }}
        </Button>
        <Button
          ref="keepButton"
          variant="outline"
          data-test="keep-open"
          :disabled="ending"
          @click="keepOpen"
        >
          {{ strings.host.keepOpen }}
        </Button>
      </div>
    </div>
    <p
      v-if="endError !== null"
      role="alert"
      class="text-sm text-destructive"
    >
      {{ endError }}
    </p>
  </Card>
</template>
