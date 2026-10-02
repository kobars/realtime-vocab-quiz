// AI-ASSISTED: shadcn-vue badge variants as clay pills: 2 px outline, role fills under night text, soft state fills, a solid offset focus ring.
import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

export const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full border-2 px-3 py-1 text-sm font-semibold w-fit whitespace-nowrap shrink-0 [&>svg]:size-4 gap-1.5 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-invalid:ring-destructive aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default: "border-primary/25 bg-secondary text-secondary-foreground",
        secondary: "border-border bg-muted text-muted-foreground",
        mint: "border-night/10 bg-mint text-night",
        cyan: "border-night/10 bg-cyan text-night",
        sun: "border-night/10 bg-sun text-night",
        success: "border-success/25 bg-success-soft text-success",
        destructive: "border-destructive/25 bg-destructive-soft text-destructive",
        warning: "border-warning/25 bg-warning-soft text-warning",
        outline: "border-input text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)
export type BadgeVariants = VariantProps<typeof badgeVariants>
