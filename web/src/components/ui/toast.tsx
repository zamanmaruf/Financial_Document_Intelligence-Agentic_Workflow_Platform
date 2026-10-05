import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type ToastTone = "info" | "ok" | "warn" | "danger";

interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
  action?: { label: string; onClick: () => void };
}

interface ToastApi {
  toast: (t: Omit<ToastItem, "id">) => void;
}

const ToastContext = createContext<ToastApi>({ toast: () => undefined });

const ICON = { info: Info, ok: CheckCircle2, warn: AlertTriangle, danger: AlertTriangle } as const;
const TONE = {
  info: "text-info",
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(0);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const toast = useCallback(
    (t: Omit<ToastItem, "id">) => {
      const id = ++next.current;
      setItems((all) => [...all.slice(-2), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.action ? 10000 : 6000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
      >
        {items.map((t) => {
          const Icon = ICON[t.tone];
          return (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex w-full max-w-sm animate-fade-up items-start gap-3 rounded-xl border border-line-strong bg-surface-overlay/95 p-4 shadow-float backdrop-blur"
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", TONE[t.tone])} aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium text-ink">{t.title}</p>
                {t.body && <p className="mt-0.5 text-ink-muted">{t.body}</p>}
                {t.action && (
                  <button
                    type="button"
                    onClick={() => {
                      t.action?.onClick();
                      dismiss(t.id);
                    }}
                    className="mt-2 text-[13px] font-medium text-brand transition-colors hover:text-ink"
                  >
                    {t.action.label}
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="rounded-md p-0.5 text-ink-subtle hover:text-ink"
                aria-label="Dismiss"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
