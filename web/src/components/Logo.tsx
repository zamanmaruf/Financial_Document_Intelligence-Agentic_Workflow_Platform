import { useId } from "react";

import { cn } from "@/lib/utils";

/** DocIntel mark: a page with a scan line resolving into a check. */
export function LogoMark({ className }: { className?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <defs>
        <linearGradient id={`${id}-g`} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#c4b8ff" />
          <stop offset="0.55" stopColor="#8b7bff" />
          <stop offset="1" stopColor="#38d5f2" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="#121419" stroke="rgb(255 255 255 / 0.1)" />
      <path
        d="M11 7.5h7.2L23 12.3V23a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 10 23V9a1.5 1.5 0 0 1 1-1.5Z"
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M13 13h4.5" stroke="rgb(255 255 255 / 0.35)" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="m13.4 18.6 2.2 2.2 4.2-4.6"
        fill="none"
        stroke={`url(#${id}-g)`}
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 font-semibold tracking-tight text-ink", className)}>
      <LogoMark />
      <span className="text-[15px]">DocIntel</span>
    </span>
  );
}
