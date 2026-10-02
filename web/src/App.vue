<!-- AI-ASSISTED: the app layout: a skip link to the main region, a sticky clay header with the wordmark, the routed screen and the toast outlet (UI spec §6.2). -->
<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import { useTemplateRef } from 'vue'
import { Toaster } from '@quiz/clay'
import { strings } from '@/strings'

const main = useTemplateRef<HTMLElement>('main')
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <!-- Above the window and transparent (also in a scrolled page) until it has the focus. It moves the focus itself: the router would read a hash as a route change. -->
    <a
      href="#main"
      data-test="skip-link"
      class="fixed top-2 left-4 z-20 inline-flex min-h-11 -translate-y-[calc(100%+1rem)] items-center opacity-0 rounded-lg border-clay bg-card px-4 font-bold text-primary shadow-press focus-hug focus-visible:translate-y-0 focus-visible:opacity-100"
      @click.prevent="main?.focus()"
    >{{ strings.skipLink }}</a>
    <header class="sticky top-0 z-10 border-b-clay bg-background supports-[backdrop-filter]:bg-background/95 supports-[backdrop-filter]:backdrop-blur-sm">
      <div class="mx-auto flex h-16 max-w-5xl items-center px-4">
        <RouterLink
          to="/"
          data-test="wordmark"
          class="-mx-2 inline-flex min-h-11 items-center gap-3 rounded-lg px-2 text-xl font-extrabold"
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
    <main
      id="main"
      ref="main"
      tabindex="-1"
      class="mx-auto w-full max-w-5xl flex-1 px-4 py-6 focus:outline-none sm:py-10"
    >
      <RouterView />
    </main>
    <Toaster />
  </div>
</template>
