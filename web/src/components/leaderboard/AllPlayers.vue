<!-- AI-ASSISTED: "Show all players": get_leaderboard pages with their atSeq, read again (at most once per second, on the monotonic clock) while the standings move or no reply came (UI spec §3.6, §6.1; protocol §3, §7). -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { PAGE_SIZE, useQuizStore } from '@/stores/quiz'
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
const rows = computed(() => page.value?.rows ?? [])
const last = computed(() => Math.min(offset.value + PAGE_SIZE, store.playerCount))

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

function show(): void {
  open.value = true
  load(0)
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
    class="flex flex-col gap-2"
    :aria-label="strings.leaderboard.showAll"
    @keydown.esc="hide"
  >
    <p class="text-sm text-muted-foreground">
      {{ strings.leaderboard.range(offset + 1, last, store.playerCount) }} ·
      <span data-test="page-seq">{{ page === null ? '' : page.final ? strings.leaderboard.final : strings.leaderboard.asOf(page.atSeq) }}</span>
    </p>
    <LeaderboardRows
      :entries="rows"
      :my-user-id="store.quiz?.userId"
      :limit="PAGE_SIZE"
      :animate="false"
    />
    <div class="flex gap-2">
      <Button
        variant="secondary"
        :disabled="offset === 0"
        @click="load(Math.max(0, offset - PAGE_SIZE))"
      >
        {{ strings.leaderboard.previous }}
      </Button>
      <Button
        variant="secondary"
        :disabled="offset + PAGE_SIZE >= store.playerCount"
        @click="load(offset + PAGE_SIZE)"
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
