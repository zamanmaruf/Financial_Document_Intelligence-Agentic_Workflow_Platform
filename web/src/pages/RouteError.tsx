import { AlertTriangle, RotateCw } from "lucide-react";
import { Link, useRouteError } from "react-router";

import { Button } from "@/components/ui/button";

/** True when a lazily loaded page's code is gone, usually because the site was redeployed. */
function isStaleChunk(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
    message,
  );
}

export function RouteError() {
  const error = useRouteError();
  const stale = isStaleChunk(error);
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-4 pb-24 pt-24 text-center">
      <span className="grid size-14 place-items-center rounded-2xl border border-line-strong bg-surface-raised text-warn shadow-card">
        <AlertTriangle className="size-6" aria-hidden />
      </span>
      <h1 className="mt-6 text-3xl font-semibold tracking-[-0.03em] text-ink">
        {stale ? "The site has been updated" : "This page ran into a problem"}
      </h1>
      <p className="mt-3 max-w-md text-ink-muted">
        {stale
          ? "A newer version went live since you opened this tab. Reload to pick it up; it takes a second."
          : "Something went wrong while showing this page. Reloading usually fixes it, and your documents aren&apos;t affected."}
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button size="lg" onClick={() => window.location.reload()}>
          <RotateCw aria-hidden /> Reload the page
        </Button>
        <Button asChild size="lg" variant="secondary">
          <Link to="/" reloadDocument>
            Back to home
          </Link>
        </Button>
      </div>
    </div>
  );
}
