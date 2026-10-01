<!-- AI-ASSISTED: "Show all players": get_leaderboard pages with their atSeq, read again (at most once per second) while the standings move (UI spec §3.6, §6.1). -->
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
let loadedAt = -Infinity
let reload: ReturnType<typeof setTimeout> | null = null

const rows = computed(() => store.allPlayers.slice(offset.value, offset.value + PAGE_SIZE))
const last = computed(() => Math.min(offset.value + PAGE_SIZE, store.playerCount))

function load(at: number): void {
  offset.value = at
  loadedAt = Date.now()
  store.loadPage(at)
}

function show(): void {
  open.value = true
  load(0)
}

function hide(): void {
  open.value = false
  if (reload !== null) clearTimeout(reload)
  reload = null
  void nextTick(() => (toggle.value?.$el as HTMLElement | undefined)?.focus())
}

// The open page is stale once a newer frame is applied; the final page never is.
watch(() => [store.seq, store.pageAtSeq, store.pageFinal] as const, ([seq, atSeq, final]) => {
  if (!open.value || final || atSeq === null || seq <= atSeq || reload !== null) return
  reload = setTimeout(() => {
    reload = null
    if (open.value) load(offset.value)
  }, Math.max(0, loadedAt + PAGE_RELOAD_MS - Date.now()))
})
onBeforeUnmount(() => reload !== null && clearTimeout(reload))
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
    class="flex flex-col gap-2"
    :aria-label="strings.leaderboard.showAll"
    @keydown.esc="hide"
  >
    <p class="text-sm text-muted-foreground">
      {{ strings.leaderboard.range(offset + 1, last, store.playerCount) }} ·
      <span data-test="page-seq">{{ store.pageFinal ? strings.leaderboard.final : store.pageAtSeq === null ? '' : strings.leaderboard.asOf(store.pageAtSeq) }}</span>
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
