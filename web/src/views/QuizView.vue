<!-- AI-ASSISTED: placeholder for the quiz screens; the client state picks the screen. -->
<script setup lang="ts">
import { strings } from '@/strings'

defineProps<{ quizId: string }>()
</script>

<template>
  <h1 class="text-2xl font-semibold">
    {{ strings.quiz.title(quizId) }}
  </h1>
</template>
