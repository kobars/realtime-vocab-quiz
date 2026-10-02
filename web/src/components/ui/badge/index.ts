// AI-ASSISTED: shadcn-vue badge variants as clay pills: 2 px outline, role fills under night text, soft state fills; not a control, so no focus styles of its own.
import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

export const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full border-2 px-3 py-1 text-sm font-semibold w-fit whitespace-nowrap shrink-0 [&>svg]:size-4 gap-1.5 [&>svg]:pointer-events-none transition-[color,box-shadow] overflow-hidden",
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
