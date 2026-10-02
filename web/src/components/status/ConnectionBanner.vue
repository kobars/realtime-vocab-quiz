<!-- AI-ASSISTED: the calm connection pill: connecting, reconnecting or updating (quiet pill), server busy (warning pill), or closed (destructive pill), wrapping on a narrow screen; nothing while live or blocked (UI spec §3.7, §6.3). -->
<script setup lang="ts">
import { computed } from 'vue'
import { badgeVariants } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
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
// Only a busy server and a lost connection stand out; the states the client recovers from on its own stay quiet.
const variant = computed(() => (store.busy !== null ? 'warning' : store.connection === 'closed' ? 'destructive' : 'secondary'))
</script>

<template>
  <!-- The live region stays in the page, so a change of its text is announced. -->
  <p
    role="status"
    data-test="connection"
    :class="text ? cn(badgeVariants({ variant }), 'whitespace-normal') : 'sr-only'"
  >
    {{ text }}
  </p>
</template>
