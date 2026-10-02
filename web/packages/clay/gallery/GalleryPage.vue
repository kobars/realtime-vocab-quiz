<!-- AI-ASSISTED: the Clay gallery: every token and every component variant and state, in the light and the dark theme side by side. -->
<script setup lang="ts">
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

const SECTIONS = [
  { id: 'colours', title: 'Colours' },
  { id: 'contrast', title: 'Contrast' },
  { id: 'type', title: 'Type' },
  { id: 'shape', title: 'Shape and depth' },
  { id: 'motion', title: 'Motion' },
  { id: 'button', title: 'Button' },
  { id: 'badge', title: 'Badge' },
  { id: 'card', title: 'Card' },
  { id: 'input', title: 'Input' },
  { id: 'progress', title: 'Progress' },
  { id: 'toast', title: 'Toaster' },
] as const
const title = (id: (typeof SECTIONS)[number]['id']) => SECTIONS.find((section) => section.id === id)?.title ?? id
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
        id="colours"
        :title="title('colours')"
      >
        <template #note>
          Every colour token with its WCAG ratio on the page and on a card.
        </template>
        <template #default="{ theme }">
          <ColourTokens :theme="theme" />
        </template>
      </GallerySection>
      <GallerySection
        id="contrast"
        :title="title('contrast')"
      >
        <template #note>
          Every pair the components draw: text needs 4.5:1, outlines and the focus ring 3:1. The package's contrast test
          checks the same list.
        </template>
        <template #default="{ theme }">
          <ContrastPairs :theme="theme" />
        </template>
      </GallerySection>
      <GallerySection
        id="type"
        :title="title('type')"
      >
        <TypeScale />
      </GallerySection>
      <GallerySection
        id="shape"
        :title="title('shape')"
      >
        <template #note>
          Light surfaces cast a hard tinted offset; dark ones a soft glow below, and controls a 2 px edge.
        </template>
        <template #default>
          <ShapeTokens />
        </template>
      </GallerySection>
      <GallerySection
        id="motion"
        :title="title('motion')"
      >
        <MotionTokens />
      </GallerySection>
      <GallerySection
        id="button"
        :title="title('button')"
      >
        <template #note>
          Filled variants keep a 2 px gap between the focus outline and the fill; outlined ones turn their own outline
          into the focus band.
        </template>
        <template #default>
          <ButtonStates />
        </template>
      </GallerySection>
      <GallerySection
        id="badge"
        :title="title('badge')"
      >
        <BadgeVariants />
      </GallerySection>
      <GallerySection
        id="card"
        :title="title('card')"
      >
        <CardStates />
      </GallerySection>
      <GallerySection
        id="input"
        :title="title('input')"
      >
        <InputStates />
      </GallerySection>
      <GallerySection
        id="progress"
        :title="title('progress')"
      >
        <ProgressStates />
      </GallerySection>
      <GallerySection
        id="toast"
        :title="title('toast')"
      >
        <template #default="{ theme }">
          <ToastStates :theme="theme" />
        </template>
      </GallerySection>
    </main>
  </div>
</template>
