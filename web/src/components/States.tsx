import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function ErrorState({
  message,
  action,
  onRetry,
  className,
}: {
  message: string;
  action?: ReactNode;
  /** Shows a "Try again" button when no other action is given. */
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-start gap-3 rounded-xl border border-danger-line bg-danger-soft p-4 sm:flex-row sm:items-center",
        className,
      )}
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-danger-soft text-danger">
        <AlertTriangle className="size-4" aria-hidden />
      </span>
      <p className="flex-1 text-sm text-ink">{message}</p>
      {action ??
        (onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex h-8 shrink-0 items-center rounded-full border border-line-strong bg-surface-raised px-3.5 text-[13px] font-medium text-ink transition-colors hover:bg-surface-overlay"
          >
            Try again
          </button>
        ))}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
  icon,
  className,
}: {
  title: string;
  body: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed border-line-strong bg-surface/60 px-6 py-10 text-center",
        className,
      )}
    >
      <span className="grid size-11 place-items-center rounded-xl border border-line-strong bg-surface-raised text-ink-muted shadow-card [&_svg]:size-5">
        {icon ?? <Inbox aria-hidden />}
      </span>
      <p className="font-medium text-ink">{title}</p>
      <p className="max-w-sm text-sm leading-relaxed text-ink-muted">{body}</p>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

const CALLOUT = {
  info: "border-info-line bg-info-soft [&_.callout-icon]:text-info",
  ok: "border-ok-line bg-ok-soft [&_.callout-icon]:text-ok",
  warn: "border-warn-line bg-warn-soft [&_.callout-icon]:text-warn",
  danger: "border-danger-line bg-danger-soft [&_.callout-icon]:text-danger",
  neutral: "border-line-strong bg-surface-raised [&_.callout-icon]:text-ink-muted",
} as const;

export function Callout({
  tone = "info",
  icon,
  title,
  children,
  className,
}: {
  tone?: keyof typeof CALLOUT;
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex gap-3 rounded-xl border p-4", CALLOUT[tone], className)}>
      {icon && <span className="callout-icon mt-0.5 shrink-0 [&_svg]:size-[18px]">{icon}</span>}
      <div className="min-w-0 space-y-1 text-sm">
        <p className="font-medium text-ink">{title}</p>
        {children && <div className="leading-relaxed text-ink-muted">{children}</div>}
      </div>
    </div>
  );
}
