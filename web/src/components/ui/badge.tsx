import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium leading-5 [&_svg]:size-3.5 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        ok: "border-ok-line bg-ok-soft text-ok",
        warn: "border-warn-line bg-warn-soft text-warn",
        danger: "border-danger-line bg-danger-soft text-danger",
        info: "border-info-line bg-info-soft text-info",
        brand: "border-brand-line bg-brand-soft text-brand",
        neutral: "border-line-strong bg-white/[0.03] text-ink-muted",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  /** A small status dot before the label; ``pulse`` animates it for live states. */
  dot?: boolean | "pulse";
}

export function Badge({ className, tone, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && (
        <span
          aria-hidden
          className={cn("size-1.5 rounded-full bg-current", dot === "pulse" && "animate-beacon")}
        />
      )}
      {children}
    </span>
  );
}
