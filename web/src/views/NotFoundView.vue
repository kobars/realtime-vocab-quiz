<!-- AI-ASSISTED: the 404 page for any unknown path, as a clay card with an icon tile and a way home. -->
<script setup lang="ts">
import { MapPinOff } from '@lucide/vue'
import { Button, Card } from '@quiz/clay'
import { strings } from '@/strings'
</script>

<template>
  <Card class="mx-auto max-w-110 items-start">
    <span
      class="flex size-16 items-center justify-center rounded-xl bg-sun text-night"
      aria-hidden="true"
    >
      <MapPinOff class="size-8" />
    </span>
    <h1 class="text-title">
      {{ strings.notFound.title }}
    </h1>
    <p class="text-muted-foreground">
      {{ strings.notFound.body }}
    </p>
    <Button
      as-child
      variant="outline"
    >
      <RouterLink to="/">
        {{ strings.notFound.home }}
      </RouterLink>
    </Button>
  </Card>
</template>
