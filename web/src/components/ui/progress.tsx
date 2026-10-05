import { cn } from "@/lib/utils";

/** A labelled meter, e.g. "4 of 6 documents left today". */
export function Meter({
  value,
  max,
  label,
  className,
}: {
  value: number;
  max: number;
  label: string;
  className?: string;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const low = pct <= 34;
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-ink-muted">{label}</span>
        <span className="num font-medium text-ink">
          {value}
          <span className="text-ink-subtle"> / {max}</span>
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500 ease-out",
            low ? "bg-warn" : "bg-gradient-to-r from-brand to-brand-2",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
