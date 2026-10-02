<!-- AI-ASSISTED: a QR code of a text drawn in the browser as one SVG path, night modules on a mint tile in both themes (a role fill under night text, so scanners always see dark on light). -->
<script setup lang="ts">
import { computed } from 'vue'
import { encode } from 'uqr'

const props = defineProps<{ value: string; label: string }>()

/** With the four-module quiet zone that scanners expect, drawn in the tile's own fill. */
const qr = computed(() => encode(props.value, { ecc: 'M', border: 4 }))
/** One unit square per dark module, so the path scales with the SVG. */
const path = computed(() =>
  qr.value.data.flatMap((row, y) => row.flatMap((dark, x) => (dark ? [`M${x} ${y}h1v1h-1z`] : []))).join(''))
</script>

<template>
  <div class="rounded-card border-2 border-night/10 bg-mint text-night">
    <svg
      role="img"
      :aria-label="label"
      :viewBox="`0 0 ${qr.size} ${qr.size}`"
      shape-rendering="crispEdges"
      class="block size-full"
    >
      <path
        :d="path"
        fill="currentColor"
      />
    </svg>
  </div>
</template>
