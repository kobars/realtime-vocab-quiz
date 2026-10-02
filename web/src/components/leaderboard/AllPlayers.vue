<!-- AI-ASSISTED: "Show all players": get_leaderboard pages, read again (at most once per second, on the monotonic clock) while the standings move or no reply came, with a loading status until a page arrives and the shown rows kept while the next one loads, in a lifted clay panel that fades in behind motion-safe (UI spec §3.6, §6.1; protocol §3, §7). -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { PAGE_SIZE, type StandingsPage, useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import LeaderboardRows from './LeaderboardRows.vue'
import { PAGE_RELOAD_MS } from './limits'

const store = useQuizStore()
const open = ref(false)
const offset = ref(0)
const toggle = useTemplateRef<InstanceType<typeof Button>>('toggle')
const panel = useTemplateRef<HTMLElement>('panel')
let loadedAt = -Infinity
let reload: ReturnType<typeof setTimeout> | null = null

/** The reply for the open offset, once it has arrived. */
const page = computed(() => (store.page?.offset === offset.value ? store.page : null))
/** The page on screen: the open offset's, or while that one loads, the page shown before it. */
const previous = ref<StandingsPage | null>(null)
watch(page, (arrived) => arrived !== null && (previous.value = arrived))
const shown = computed(() => page.value ?? previous.value)
const last = computed(() => Math.min((shown.value?.offset ?? 0) + PAGE_SIZE, store.playerCount))

function cancel(): void {
  if (reload !== null) clearTimeout(reload)
  reload = null
}

function load(at: number): void {
  cancel()
  offset.value = at
  loadedAt = store.now()
  store.loadPage(at)
}

/** Pages to `at`. A pager button that this disables loses the focus, so the panel takes it and Escape still works. */
function go(at: number): void {
  load(at)
  void nextTick(() => {
    const focused = document.activeElement
    if (panel.value?.contains(focused) !== true || focused?.matches(':disabled') === true) panel.value?.focus()
  })
}

function show(): void {
  open.value = true
  load(0)
  // The stored reply for offset 0, if any, is the fallback too: `page` keeps the same object, so its watcher stays quiet.
  previous.value = page.value
  void nextTick(() => panel.value?.focus())
}

function hide(): void {
  open.value = false
  cancel()
  void nextTick(() => (toggle.value?.$el as HTMLElement | undefined)?.focus())
}

// The open page is stale while no reply for it came (dropped or refused: retry, protocol §7), or once its standings
// differ from the applied ones (a lower seq is a store restart, protocol §3); the final page never is.
const stale = (): boolean => open.value && (page.value === null || (!page.value.final && page.value.atSeq !== store.seq))

function schedule(): void {
  if (reload !== null || !stale()) return
  reload = setTimeout(() => {
    reload = null
    if (!stale()) return
    if (store.now() - loadedAt >= PAGE_RELOAD_MS) load(offset.value)
    schedule()
  }, Math.max(0, loadedAt + PAGE_RELOAD_MS - store.now()))
}

watch(() => [open.value, store.seq, page.value, store.connection, store.lastError], schedule)
onBeforeUnmount(cancel)
</script>

<template>
  <Button
    v-if="!open"
    ref="toggle"
    variant="outline"
    @click="show"
  >
    {{ strings.leaderboard.showAll }}
  </Button>
  <section
    v-else
    ref="panel"
    tabindex="-1"
    class="flex flex-col gap-3 rounded-card border-clay bg-card p-4 shadow-clay-lift motion-safe:animate-fade-in"
    :aria-label="strings.leaderboard.showAll"
    @keydown.esc="hide"
  >
    <!-- The live region stays in the panel, so the loading text is announced when it appears. -->
    <p
      role="status"
      data-test="page-status"
      :class="page === null ? 'text-sm text-muted-foreground' : 'sr-only'"
    >
      {{ page === null ? strings.leaderboard.loading : '' }}
    </p>
    <p
      v-if="shown !== null"
      data-test="page-range"
      class="text-sm text-muted-foreground"
    >
      {{ strings.leaderboard.range(shown.offset + 1, last, store.playerCount) }}{{ shown.final ? ` · ${strings.leaderboard.final}` : '' }}
    </p>
    <LeaderboardRows
      :entries="shown?.rows ?? []"
      :my-user-id="store.quiz?.userId"
      :limit="PAGE_SIZE"
      :animate="false"
    />
    <div class="flex flex-wrap gap-2">
      <Button
        variant="secondary"
        :disabled="offset === 0"
        @click="go(Math.max(0, offset - PAGE_SIZE))"
      >
        {{ strings.leaderboard.previous }}
      </Button>
      <Button
        variant="secondary"
        :disabled="offset + PAGE_SIZE >= store.playerCount"
        @click="go(offset + PAGE_SIZE)"
      >
        {{ strings.leaderboard.next }}
      </Button>
      <Button
        variant="ghost"
        @click="hide"
      >
        {{ strings.leaderboard.close }}
      </Button>
    </div>
  </section>
</template>
