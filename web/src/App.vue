<!-- AI-ASSISTED: the app layout: a header, the routed screen and the toast outlet. -->
<script setup lang="ts">
import { Toaster } from '@/components/ui/sonner'
import { strings } from '@/strings'
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <header class="border-b bg-card">
      <div class="mx-auto flex h-14 max-w-5xl items-center px-4">
        <RouterLink
          to="/"
          class="rounded-md font-semibold focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          {{ strings.appName }}
        </RouterLink>
      </div>
    </header>
    <main class="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
      <RouterView />
    </main>
    <Toaster />
  </div>
</template>
