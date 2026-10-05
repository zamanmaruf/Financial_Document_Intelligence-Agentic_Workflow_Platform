import { lazy, Suspense } from "react";

import { cn } from "@/lib/utils";

import type { DocumentViewerProps } from "./DocumentViewer";

export type { DocumentViewerProps } from "./DocumentViewer";
export * from "./highlights";

const Impl = lazy(() => import("./DocumentViewer"));

export function ViewerSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("flex flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-card", className)}
    >
      <div className="flex h-12 items-center justify-between border-b border-line px-3">
        <span className="skeleton h-5 w-28 rounded-full" />
        <span className="skeleton h-5 w-24 rounded-full" />
      </div>
      <div className="bg-[#0b0c0f] p-3 sm:p-5">
        <div className="skeleton mx-auto aspect-[1/1.4142] w-full max-w-[860px] rounded-[3px] opacity-60" />
      </div>
    </div>
  );
}

/** The page viewer, loaded on first use so it stays out of the main bundle. */
export function DocumentViewer(props: DocumentViewerProps) {
  return (
    <Suspense fallback={<ViewerSkeleton className={props.className} />}>
      <Impl key={props.documentId} {...props} />
    </Suspense>
  );
}
