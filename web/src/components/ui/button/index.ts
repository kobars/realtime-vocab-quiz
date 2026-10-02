// AI-ASSISTED: shadcn-vue button variants as clay buttons: 3 px outline, hard press shadow, a lift and press behind motion-safe, a solid offset focus ring, every size at least 44 px.
import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Button } from "./Button.vue"

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border-clay text-base font-bold transition-[color,background-color,border-color,box-shadow,transform] duration-fast ease-spring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-invalid:ring-destructive aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default:
          "border-night/10 bg-gradient-primary text-primary-foreground shadow-press hover:shadow-press-hover active:shadow-press-active motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0.5",
        destructive:
          "border-night/10 bg-destructive text-destructive-foreground shadow-press hover:shadow-press-hover active:shadow-press-active motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0.5",
        mint:
          "border-night/10 bg-mint text-night shadow-press hover:shadow-press-hover active:shadow-press-active motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0.5",
        outline:
          "border-input bg-card text-primary shadow-press hover:border-primary-hover hover:bg-primary-hover hover:text-primary-foreground hover:shadow-press-hover active:shadow-press-active motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0.5",
        secondary:
          "border-border bg-secondary text-secondary-foreground hover:border-input",
        ghost:
          "border-transparent hover:bg-accent hover:text-accent-foreground",
        link: "border-transparent text-primary underline-offset-4 hover:underline",
      },
      size: {
        "default": "h-11 px-6 has-[>svg]:px-5",
        "sm": "h-11 gap-1.5 px-4 text-sm has-[>svg]:px-3",
        "lg": "h-14 px-8 text-lg has-[>svg]:px-7",
        "icon": "size-11",
        "icon-lg": "size-14",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)
export type ButtonVariants = VariantProps<typeof buttonVariants>
