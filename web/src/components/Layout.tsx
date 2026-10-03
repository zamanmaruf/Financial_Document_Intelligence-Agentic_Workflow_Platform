import { FileCheck2, Code2, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { AiBadge } from "@/components/AiBadge";
import { cn } from "@/lib/utils";

export const GITHUB_URL =
  "https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform";

const NAV = [
  { to: "/tour", label: "Guided tour" },
  { to: "/try", label: "Try it yourself" },
  { to: "/how-it-works", label: "How it works" },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-brand-soft text-brand" : "text-ink-muted hover:bg-surface-muted hover:text-ink",
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:shadow-raised"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 font-semibold text-ink">
            <span className="grid size-8 place-items-center rounded-md bg-brand text-brand-ink">
              <FileCheck2 className="size-4" aria-hidden />
            </span>
            DocIntel
          </Link>
          <nav aria-label="Main" className="ml-4 hidden items-center gap-1 md:flex">
            <NavItems />
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <AiBadge />
            <button
              type="button"
              className="rounded-md p-2 text-ink-muted hover:bg-surface-muted md:hidden"
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? <X className="size-5" /> : <Menu className="size-5" />}
            </button>
          </div>
        </div>
        {open && (
          <nav aria-label="Main" className="flex flex-col gap-1 border-t border-line px-4 py-3 md:hidden">
            <NavItems onNavigate={() => setOpen(false)} />
          </nav>
        )}
      </header>

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-ink-muted sm:px-6 md:flex-row md:items-center md:justify-between">
          <p className="max-w-xl">
            A portfolio demo. All sample documents are synthetic. Files you upload are deleted
            after 24 hours. Please don't upload real financial documents.
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <a className="inline-flex items-center gap-1.5 hover:text-ink" href={GITHUB_URL} target="_blank" rel="noreferrer">
              <Code2 className="size-4" aria-hidden /> Source code
            </a>
            <a className="hover:text-ink" href="/ui/">
              Engineer view
            </a>
            <a className="hover:text-ink" href="/docs">
              API reference
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
