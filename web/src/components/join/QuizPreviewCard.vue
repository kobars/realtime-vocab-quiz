<!-- AI-ASSISTED: the quiz preview card on the join screen: title, question and player counts, and whether the quiz has ended. -->
<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import type { QuizPreview } from '@/components/join/preview'
import { strings } from '@/strings'

defineProps<{ quiz: QuizPreview }>()
</script>

<template>
  <div class="flex flex-col gap-2 rounded-md border bg-card p-4 shadow-card">
    <div class="flex items-center justify-between gap-3">
      <p class="font-semibold">
        {{ quiz.title }}
      </p>
      <Badge :variant="quiz.status === 'ended' ? 'secondary' : 'default'">
        {{ quiz.status === 'ended' ? strings.join.preview.ended : strings.join.preview.open }}
      </Badge>
    </div>
    <p class="text-sm text-muted-foreground tabular-nums">
      {{ strings.join.preview.questions(quiz.questionCount) }} · {{ strings.join.preview.players(quiz.players) }}
    </p>
    <p
      v-if="quiz.status === 'ended'"
      class="text-sm"
    >
      {{ strings.join.ended }}
    </p>
  </div>
</template>
