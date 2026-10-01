<!-- AI-ASSISTED: answer feedback: correct or wrong, the correct choice, the points with the speed bonus counting up, and the next action (UI spec §3.4). -->
<script setup lang="ts">
import { Check, X } from '@lucide/vue'
import { computed, nextTick, onMounted, useTemplateRef } from 'vue'
import { Button } from '@/components/ui/button'
import type { AnswerResult } from '@/protocol/types.generated'
import { useQuizStore } from '@/stores/quiz'
import { strings } from '@/strings'
import { useCountUp } from './motion'

const props = defineProps<{ result: AnswerResult; choices: readonly string[]; questionCount: number }>()
const store = useQuizStore()
const button = useTemplateRef<{ $el: HTMLElement }>('button')
const points = useCountUp(() => props.result.pointsAwarded, 0)
// A correct answer on time scores 100 plus a speed bonus of up to 50.
const bonus = computed(() => (props.result.correct && !props.result.late ? props.result.pointsAwarded - 100 : 0))
const last = computed(() => props.result.questionIndex + 1 >= props.questionCount)
onMounted(() => void nextTick(() => button.value?.$el.focus()))

function mark(i: number): { label: string; good: boolean } | null {
  if (i === props.result.choiceIndex) return props.result.correct ? { label: strings.quiz.correct, good: true } : { label: strings.quiz.wrong, good: false }
  return i === props.result.correctChoiceIndex ? { label: strings.quiz.correctAnswer, good: true } : null
}
</script>

<template>
  <section class="flex flex-col gap-4">
    <h2
      class="flex items-center gap-2 text-2xl font-semibold"
      :class="result.correct ? 'text-success' : 'text-destructive'"
    >
      <component
        :is="result.correct ? Check : X"
        class="size-6"
        aria-hidden="true"
      />
      {{ result.correct ? strings.quiz.correct : strings.quiz.wrong }}
    </h2>
    <p
      data-test="points"
      class="text-xl font-semibold tabular-nums"
    >
      <template v-if="result.late">
        {{ strings.quiz.late }}
      </template>
      <template v-else>
        {{ strings.quiz.points(points) }}
        <span
          v-if="bonus > 0"
          class="text-base font-normal text-muted-foreground"
        >{{ strings.quiz.bonus(bonus) }}</span>
      </template>
    </p>
    <ul class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <li
        v-for="(choice, i) in choices"
        :key="i"
        :data-choice="i"
        class="flex min-h-11 items-center gap-3 rounded-lg border px-4 py-3 text-xl"
        :class="mark(i) === null ? 'border-input bg-card' : mark(i)?.good ? 'border-success bg-success-soft' : 'border-destructive bg-destructive-soft'"
      >
        <span class="flex-1">{{ choice }}</span>
        <span
          v-if="mark(i)"
          class="flex items-center gap-1 text-sm font-semibold"
          :class="mark(i)?.good ? 'text-success' : 'text-destructive'"
        >
          <component
            :is="mark(i)?.good ? Check : X"
            class="size-4"
            aria-hidden="true"
          />{{ mark(i)?.label }}
        </span>
      </li>
    </ul>
    <Button
      ref="button"
      class="self-start"
      @click="store.next()"
    >
      {{ last ? strings.quiz.seeResult : strings.quiz.nextQuestion }}
    </Button>
  </section>
</template>
