// AI-ASSISTED: the interaction states the gallery shows at rest: data-preview turns on the matching Tailwind variant (gallery.css).
export interface State {
  name: string
  preview?: 'hover' | 'active' | 'focus'
  disabled?: boolean
}

export const STATES: State[] = [
  { name: 'rest' },
  { name: 'hover', preview: 'hover' },
  { name: 'active', preview: 'active' },
  { name: 'focus', preview: 'focus' },
  { name: 'disabled', disabled: true },
]
