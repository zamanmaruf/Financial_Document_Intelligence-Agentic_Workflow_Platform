import { ArrowRight, FileQuestion } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";

const PLACES = [
  { to: "/tour", title: "Guided tour", body: "Eight short steps, about three minutes." },
  { to: "/try", title: "Try it yourself", body: "Open a sample or upload a PDF." },
  { to: "/how-it-works", title: "How it works", body: "What each step does, and its limits." },
];

export function NotFound() {
  return (
    <div className="relative overflow-hidden">
      <div aria-hidden className="bg-grid absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_70%)]" />
      <div aria-hidden className="glow-hero absolute inset-x-0 top-0 h-80 opacity-60" />
      <div className="relative mx-auto flex max-w-2xl flex-col items-center px-4 pb-24 pt-20 text-center sm:pt-28">
        <span className="grid size-14 place-items-center rounded-2xl border border-line-strong bg-surface-raised text-ink-muted shadow-card">
          <FileQuestion className="size-6" aria-hidden />
        </span>
        <p className="num mt-6 text-sm font-medium tracking-[0.2em] text-brand">404</p>
        <h1 className="mt-2 text-4xl font-semibold tracking-[-0.035em] text-ink sm:text-5xl">
          This page isn&apos;t in the document
        </h1>
        <p className="mt-4 max-w-md text-ink-muted">
          The link may be out of date or mistyped. Here&apos;s where you can go instead.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Button asChild size="lg">
            <Link to="/">Back to home</Link>
          </Button>
          <Button asChild size="lg" variant="secondary">
            <Link to="/tour">Start the tour</Link>
          </Button>
        </div>
        <ul className="mt-14 grid w-full gap-3 text-left sm:grid-cols-3">
          {PLACES.map((p) => (
            <li key={p.to}>
              <Link
                to={p.to}
                className="group flex h-full flex-col gap-1 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-raised"
              >
                <span className="flex items-center justify-between text-sm font-medium text-ink">
                  {p.title}
                  <ArrowRight
                    className="size-3.5 text-ink-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-ink"
                    aria-hidden
                  />
                </span>
                <span className="text-xs leading-relaxed text-ink-muted">{p.body}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
