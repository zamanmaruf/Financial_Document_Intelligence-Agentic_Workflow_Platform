import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export type StepperState = "done" | "current" | "upcoming";

export interface StepperItem {
  title: string;
  state: StepperState;
  hint?: string;
}

/** Vertical step rail: numbered dots joined by a line, done steps ticked. */
export function Stepper({
  items,
  onSelect,
  label,
  className,
}: {
  items: StepperItem[];
  onSelect?: (index: number) => void;
  label: string;
  className?: string;
}) {
  return (
    <ol aria-label={label} className={cn("relative space-y-0.5", className)}>
      {items.map((item, i) => {
        const last = i === items.length - 1;
        return (
          <li key={item.title} className="relative">
            {!last && (
              <span
                aria-hidden
                className={cn(
                  "absolute left-[19px] top-[26px] h-[calc(100%-16px)] w-px",
                  item.state === "done" ? "bg-gradient-to-b from-brand/60 to-line-strong" : "bg-line-strong",
                )}
              />
            )}
            <button
              type="button"
              onClick={() => onSelect?.(i)}
              aria-current={item.state === "current" ? "step" : undefined}
              className={cn(
                "group relative flex w-full items-center gap-3 rounded-lg px-1.5 py-1.5 text-left transition-colors",
                item.state === "current" ? "bg-white/[0.04]" : "hover:bg-white/[0.03]",
              )}
            >
              <span
                className={cn(
                  "num relative grid size-[19px] shrink-0 place-items-center rounded-full border text-[10px] font-semibold transition-colors",
                  "ml-1",
                  item.state === "done" && "border-brand/70 bg-brand/15 text-brand",
                  item.state === "current" && "border-ink bg-ink text-canvas shadow-[0_0_0_4px_rgb(237_238_240/0.08)]",
                  item.state === "upcoming" && "border-line-bright bg-canvas text-ink-subtle",
                )}
              >
                {item.state === "done" ? <Check className="size-3" strokeWidth={3} aria-hidden /> : i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    "block truncate text-[13px]",
                    item.state === "current" ? "font-medium text-ink" : "text-ink-muted group-hover:text-ink",
                  )}
                >
                  {item.title}
                </span>
              </span>
              {item.hint && <span className="text-[11px] text-ink-subtle">{item.hint}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
