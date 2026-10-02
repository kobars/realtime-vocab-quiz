// AI-ASSISTED: class-name helper that the shadcn-vue components import, taught the clay utilities of theme.css.
import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// Without these groups tailwind-merge reads `border-clay` as a border color and `text-title` as a text color,
// so a later `border-input` or `text-night` would drop them.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'border-w': [{ border: ['clay'] }],
      'border-w-b': [{ 'border-b': ['clay'] }],
      'font-size': [{ text: ['title', 'display'] }],
      'bg-image': [{ bg: ['gradient-primary'] }],
      rounded: [{ rounded: ['card'] }],
      shadow: [{ shadow: ['clay', 'clay-lift', 'press', 'press-hover', 'press-active', 'inset'] }],
    },
  },
})

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
