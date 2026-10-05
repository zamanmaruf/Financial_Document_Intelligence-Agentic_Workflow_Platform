import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        "inline-grid h-5 min-w-5 place-items-center rounded-md border border-line-strong bg-surface-raised px-1 font-mono text-[11px] leading-none text-ink-muted shadow-[inset_0_-1px_0_rgb(255_255_255/0.06)]",
        className,
      )}
      {...props}
    />
  );
}
