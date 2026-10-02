<!-- AI-ASSISTED: the app layout: a sticky clay header with the wordmark, the routed screen and the toast outlet. -->
<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import { Toaster } from '@/components/ui/sonner'
import { strings } from '@/strings'
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <header class="sticky top-0 z-10 border-b-clay bg-background supports-[backdrop-filter]:bg-background/95 supports-[backdrop-filter]:backdrop-blur-sm">
      <div class="mx-auto flex h-16 max-w-5xl items-center px-4">
        <RouterLink
          to="/"
          data-test="wordmark"
          class="-mx-2 inline-flex min-h-11 items-center gap-3 rounded-lg px-2 text-xl font-extrabold focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <span
            class="flex size-10 items-center justify-center rounded-xl bg-gradient-primary text-primary-foreground"
            aria-hidden="true"
          >
            <Sparkles class="size-5" />
          </span>
          <span class="text-gradient">{{ strings.appName }}</span>
        </RouterLink>
      </div>
    </header>
    <main class="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:py-10">
      <RouterView />
    </main>
    <Toaster />
  </div>
</template>
