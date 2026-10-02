<!-- AI-ASSISTED: the calm connection pill: connecting, reconnecting, updating, server busy (warning pill), or closed (destructive pill); nothing while live or blocked (UI spec §3.7, §6.3). -->
<script setup lang="ts">
import { computed } from 'vue'
import { badgeVariants } from '@/components/ui/badge'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'

const store = useQuizStore()
const text = computed(() => {
  // A blocked screen shows its card instead (ErrorMessage).
  if (store.blocked !== null) return ''
  if (store.busy !== null) return strings.connection.busy
  switch (store.connection) {
    case 'connecting':
    case 'reconnecting':
    case 'resyncing':
      return strings.connection[store.connection]
    case 'closed':
      // 1000 is a normal close: the quiz ended or the player left.
      return store.closeCode === 1000 ? '' : strings.connection.closed
    case 'idle':
    case 'joined':
      return ''
  }
})
</script>

<template>
  <!-- The live region stays in the page, so a change of its text is announced. -->
  <p
    role="status"
    data-test="connection"
    :class="text ? badgeVariants({ variant: store.connection === 'closed' ? 'destructive' : 'warning' }) : 'sr-only'"
  >
    {{ text }}
  </p>
</template>
