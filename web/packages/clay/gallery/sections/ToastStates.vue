<!-- AI-ASSISTED: each toast type in a Toaster of the panel's own; the frame contains the toaster's fixed position. -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { toast, Toaster } from '../../src'
import type { Theme } from '../theme'

const props = defineProps<{ theme: Theme }>()
const id = `toaster-${props.theme}`

onMounted(() => {
  const options = { toasterId: id, duration: Number.POSITIVE_INFINITY }
  toast('Quiz starts in 10 s', options)
  toast.success('Answer saved', options)
  toast.warning('Server busy, retrying', options)
  toast.error('Connection lost', options)
})
</script>

<template>
  <div class="relative h-80 overflow-hidden rounded-lg border-2 border-dashed border-border contain-layout">
    <Toaster
      :id="id"
      position="top-center"
      expand
      :visible-toasts="4"
    />
  </div>
</template>
