<!-- AI-ASSISTED: the 404 page for any unknown path. -->
<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { strings } from '@/strings'
</script>

<template>
  <section class="flex flex-col items-start gap-4">
    <h1 class="text-2xl font-semibold">
      {{ strings.notFound.title }}
    </h1>
    <p class="text-muted-foreground">
      {{ strings.notFound.body }}
    </p>
    <Button as-child>
      <RouterLink to="/">
        {{ strings.notFound.home }}
      </RouterLink>
    </Button>
  </section>
</template>
