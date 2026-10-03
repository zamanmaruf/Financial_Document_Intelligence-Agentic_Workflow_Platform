import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-24 text-center">
      <p className="text-sm font-medium text-brand">Page not found</p>
      <h1 className="text-3xl font-semibold text-ink">There's nothing here</h1>
      <p className="text-ink-muted">The link may be out of date. The tour is a good place to start.</p>
      <div className="flex gap-2">
        <Button asChild>
          <Link to="/tour">Start the tour</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/">Home</Link>
        </Button>
      </div>
    </div>
  );
}
