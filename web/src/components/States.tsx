import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function ErrorState({
  message,
  action,
  className,
}: {
  message: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4 sm:flex-row sm:items-center", className)}
    >
      <AlertTriangle className="size-5 shrink-0 text-danger" aria-hidden />
      <p className="flex-1 text-sm text-ink">{message}</p>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface p-8 text-center">
      <Inbox className="size-8 text-ink-subtle" aria-hidden />
      <p className="font-medium text-ink">{title}</p>
      <p className="max-w-sm text-sm text-ink-muted">{body}</p>
      {action}
    </div>
  );
}

export function Callout({
  tone = "info",
  icon,
  title,
  children,
}: {
  tone?: "info" | "ok" | "warn" | "danger";
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  const styles = {
    info: "border-info/25 bg-info-soft",
    ok: "border-ok/25 bg-ok-soft",
    warn: "border-warn/30 bg-warn-soft",
    danger: "border-danger/30 bg-danger-soft",
  }[tone];
  return (
    <div className={cn("flex gap-3 rounded-lg border p-4", styles)}>
      {icon && <span className="mt-0.5 shrink-0 [&_svg]:size-5">{icon}</span>}
      <div className="space-y-1 text-sm">
        <p className="font-semibold text-ink">{title}</p>
        {children && <div className="text-ink-muted">{children}</div>}
      </div>
    </div>
  );
}
