import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

/** A row of mutually exclusive toggle buttons (aria-pressed), for switching a view. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-line bg-surface p-1", className)}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={o.disabled}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-xl px-3 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-40",
            value === o.value ? "bg-surface-overlay text-ink shadow-card" : "text-ink-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
