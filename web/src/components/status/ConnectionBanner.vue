<!-- AI-ASSISTED: the calm connection pill: connecting, reconnecting, updating, or closed; nothing while live (UI spec §3.7, §6.3). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const store = useQuizStore()
const text = computed(() => {
  switch (store.connection) {
    case 'connecting':
    case 'reconnecting':
    case 'resyncing':
      return strings.connection[store.connection]
    case 'closed':
      // 1000 is a normal close: the quiz ended or the player left (or another tab took over; the error says so).
      return store.closeCode === 1000 ? '' : strings.connection.closed
    default:
      return ''
  }
})
</script>

<template>
  <!-- The live region stays in the page, so a change of its text is announced. -->
  <p
    role="status"
    data-test="connection"
    :class="text ? 'self-start rounded-full bg-muted px-3 py-1 text-sm text-muted-foreground' : 'sr-only'"
  >
    {{ text }}
  </p>
</template>
