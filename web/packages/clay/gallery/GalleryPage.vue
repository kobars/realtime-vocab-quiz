<!-- AI-ASSISTED: the Clay gallery: every token and every component variant and state, in the light and the dark theme side by side. -->
<script setup lang="ts">
import type { Component } from 'vue'
import { Button } from '../src'
import GallerySection from './GallerySection.vue'
import BadgeVariants from './sections/BadgeVariants.vue'
import ButtonStates from './sections/ButtonStates.vue'
import CardStates from './sections/CardStates.vue'
import ColourTokens from './sections/ColourTokens.vue'
import ContrastPairs from './sections/ContrastPairs.vue'
import InputStates from './sections/InputStates.vue'
import MotionTokens from './sections/MotionTokens.vue'
import ProgressStates from './sections/ProgressStates.vue'
import ShapeTokens from './sections/ShapeTokens.vue'
import ToastStates from './sections/ToastStates.vue'
import TypeScale from './sections/TypeScale.vue'

// Each section's specimens; a themed one takes the theme it renders in as a prop, the others follow the panel's tokens.
const SECTIONS: { id: string; title: string; component: Component; themed?: boolean; note?: string }[] = [
  { id: 'colours', title: 'Colours', component: ColourTokens, themed: true, note: 'Every colour token with its WCAG ratio on the page and on a card.' },
  {
    id: 'contrast',
    title: 'Contrast',
    component: ContrastPairs,
    themed: true,
    note: "Every pair the components draw: text needs 4.5:1, outlines and the focus ring 3:1. The package's contrast test checks the same list.",
  },
  { id: 'type', title: 'Type', component: TypeScale },
  {
    id: 'shape',
    title: 'Shape and depth',
    component: ShapeTokens,
    note: 'Light surfaces cast a hard tinted offset; dark ones a soft glow below, and controls a 2 px edge.',
  },
  { id: 'motion', title: 'Motion', component: MotionTokens },
  {
    id: 'button',
    title: 'Button',
    component: ButtonStates,
    note: 'Filled variants keep a 2 px gap between the focus outline and the fill; outlined ones turn their own outline into the focus band.',
  },
  { id: 'badge', title: 'Badge', component: BadgeVariants },
  { id: 'card', title: 'Card', component: CardStates },
  { id: 'input', title: 'Input', component: InputStates },
  { id: 'progress', title: 'Progress', component: ProgressStates },
  { id: 'toast', title: 'Toaster', component: ToastStates, themed: true },
]
</script>

<template>
  <div class="mx-auto flex max-w-7xl flex-col gap-12 px-4 py-8 sm:px-8">
    <header class="flex flex-col gap-4">
      <h1 class="text-title sm:text-display">
        <span class="text-gradient">Clay</span> design system
      </h1>
      <p class="max-w-prose text-muted-foreground">
        The tokens and components of <code>@quiz/clay</code>. Each section shows the light theme next to the dark one;
        the app picks one from the OS setting. A state such as hover or focus is shown at rest through a
        <code>data-preview</code> attribute that only this page understands.
      </p>
      <nav aria-label="Sections">
        <ul class="flex flex-wrap gap-x-2">
          <li
            v-for="section in SECTIONS"
            :key="section.id"
          >
            <Button
              as="a"
              variant="link"
              size="sm"
              :href="`#${section.id}`"
            >
              {{ section.title }}
            </Button>
          </li>
        </ul>
      </nav>
    </header>

    <main class="flex flex-col gap-16">
      <GallerySection
        v-for="section in SECTIONS"
        :id="section.id"
        :key="section.id"
        :title="section.title"
      >
        <template
          v-if="section.note"
          #note
        >
          {{ section.note }}
        </template>
        <template #default="{ theme }">
          <component
            :is="section.component"
            v-bind="section.themed ? { theme } : {}"
          />
        </template>
      </GallerySection>
    </main>
  </div>
</template>
