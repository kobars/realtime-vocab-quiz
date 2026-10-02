<!-- AI-ASSISTED: the quiz preview card on the join screen: an icon tile, the title, whether the quiz has ended, and the question and player counts as pills; it sits inside the join card, so it has an outline but no shadow of its own. -->
<script setup lang="ts">
import { BookOpenText } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import type { QuizPreview } from '@/components/join/preview'
import { strings } from '@/strings'

defineProps<{ quiz: QuizPreview }>()
</script>

<template>
  <div class="flex items-start gap-4 rounded-card border-clay bg-card p-4">
    <span
      class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-cyan text-night"
      aria-hidden="true"
    >
      <BookOpenText class="size-6" />
    </span>
    <div class="flex min-w-0 flex-1 flex-col gap-2">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="font-extrabold">
          {{ quiz.title }}
        </p>
        <Badge :variant="quiz.status === 'ended' ? 'secondary' : 'mint'">
          {{ quiz.status === 'ended' ? strings.join.preview.ended : strings.join.preview.open }}
        </Badge>
      </div>
      <div class="flex flex-wrap gap-2 tabular-nums">
        <Badge variant="cyan">
          {{ strings.join.preview.questions(quiz.questionCount) }}
        </Badge>
        <Badge variant="sun">
          {{ strings.join.preview.players(quiz.players) }}
        </Badge>
      </div>
      <p
        v-if="quiz.status === 'ended'"
        class="text-sm"
      >
        {{ strings.join.ended }}
      </p>
    </div>
  </div>
</template>
