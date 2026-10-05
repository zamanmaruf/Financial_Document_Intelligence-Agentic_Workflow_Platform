import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  [
    "relative inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium",
    "transition-[background-color,border-color,color,box-shadow,transform] duration-200 ease-out",
    "active:translate-y-px disabled:pointer-events-none disabled:opacity-45",
    "[&_svg]:size-4 [&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-ink shadow-[inset_0_-1px_0_rgb(0_0_0/0.18),0_1px_2px_rgb(0_0_0/0.4)] hover:bg-primary-hover hover:shadow-glow",
        secondary:
          "border border-line-strong bg-surface-raised text-ink shadow-card hover:border-line-bright hover:bg-surface-overlay",
        ghost: "text-ink-muted hover:bg-white/[0.05] hover:text-ink",
        success: "bg-ok text-canvas hover:brightness-110 hover:shadow-[0_0_0_1px_rgb(61_220_151/0.4),0_8px_24px_-6px_rgb(61_220_151/0.45)]",
        danger: "border border-danger-line bg-danger-soft text-danger hover:border-danger",
        link: "rounded-sm px-0 text-brand underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3.5 text-[13px]",
        md: "h-10 px-5 text-sm",
        lg: "h-12 px-6 text-[15px]",
        icon: "size-9",
      },
    },
    compoundVariants: [{ variant: "link", class: "h-auto px-0" }],
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Shows a spinner in place of the leading icon and disables the button. */
  loading?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  if (asChild) {
    return (
      <Slot className={cn(buttonVariants({ variant, size }), className)} {...props}>
        {children}
      </Slot>
    );
  }
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
