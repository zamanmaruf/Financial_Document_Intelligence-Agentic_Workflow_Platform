import { ArrowRight, Code2, Menu, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigation } from "react-router";

import { AiBadge } from "@/components/AiBadge";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const GITHUB_URL =
  "https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform";

const NAV = [
  { to: "/tour", label: "Guided tour" },
  { to: "/try", label: "Try it yourself" },
  { to: "/how-it-works", label: "How it works" },
];

function DesktopNav() {
  const location = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const pillRef = useRef<HTMLSpanElement>(null);

  // Slide the highlight under the active link; written straight to the DOM (no re-render).
  useLayoutEffect(() => {
    const nav = navRef.current;
    const pill = pillRef.current;
    if (!nav || !pill) return;
    const place = () => {
      const active = nav.querySelector<HTMLAnchorElement>('a[aria-current="page"]');
      if (!active) {
        pill.style.opacity = "0";
        return;
      }
      pill.style.opacity = "1";
      pill.style.width = `${active.offsetWidth}px`;
      pill.style.transform = `translateX(${active.offsetLeft}px)`;
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [location.pathname]);

  return (
    <nav ref={navRef} aria-label="Main" className="relative ml-6 hidden items-center md:flex">
      <span
        ref={pillRef}
        aria-hidden
        className="absolute left-0 top-0 h-full rounded-full bg-white/[0.06] opacity-0 transition-[transform,width,opacity] duration-300 ease-out"
      />
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              "relative rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors",
              isActive ? "text-ink" : "text-ink-muted hover:text-ink",
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function MobileSheet({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    panelRef.current?.querySelector<HTMLElement>("a")?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-x-0 bottom-0 top-14 z-40 md:hidden">
      <button
        type="button"
        aria-label="Close menu"
        tabIndex={-1}
        className="absolute inset-0 animate-fade-in bg-canvas/70 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        id="mobile-menu"
        className="relative animate-fade-up border-b border-line bg-surface px-4 pb-6 pt-3 shadow-float"
      >
        <nav aria-label="Main" className="flex flex-col">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "flex items-center justify-between border-b border-line py-3.5 text-base font-medium",
                  isActive ? "text-ink" : "text-ink-muted",
                )
              }
            >
              {item.label}
              <ArrowRight className="size-4 text-ink-subtle" aria-hidden />
            </NavLink>
          ))}
        </nav>
        <div className="mt-5 flex items-center justify-between gap-3">
          <AiBadge />
          <Button asChild size="sm">
            <Link to="/tour" onClick={onClose}>
              Start tour
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

function FooterLink({ href, children, external }: { href: string; children: ReactNode; external?: boolean }) {
  const cls = "text-ink-muted transition-colors hover:text-ink";
  if (external === undefined) {
    return (
      <Link to={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} className={cls} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>
      {children}
    </a>
  );
}

/** A thin bar under the header while the next page's code loads. */
function RouteProgress() {
  const loading = useNavigation().state === "loading";
  if (!loading) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-14 z-50 h-0.5 overflow-hidden" role="progressbar" aria-label="Loading page">
      <div className="h-full w-2/5 animate-route bg-gradient-to-r from-transparent via-brand to-transparent" />
    </div>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  const [lastPath, setLastPath] = useState(location.pathname);
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname);
    setOpen(false);
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-[70] focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-ink"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-50 border-b border-line bg-canvas/75 backdrop-blur-xl backdrop-saturate-150">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:px-6">
          <Link to="/" aria-label="DocIntel home" className="rounded-lg">
            <Logo />
          </Link>
          <DesktopNav />
          <div className="ml-auto flex items-center gap-2">
            <AiBadge className="hidden sm:inline-flex" />
            <Button
              asChild
              size="sm"
              className={cn("hidden md:inline-flex", location.pathname.startsWith("/tour") && "md:hidden")}
            >
              <Link to="/tour">
                Start tour <ArrowRight aria-hidden />
              </Link>
            </Button>
            <button
              type="button"
              className="grid size-9 place-items-center rounded-full text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink md:hidden"
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              aria-controls="mobile-menu"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
            </button>
          </div>
        </div>
      </header>
      {open && <MobileSheet onClose={() => setOpen(false)} />}

      <RouteProgress />
      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.6fr_1fr_1fr]">
          <div className="space-y-3">
            <Logo />
            <p className="max-w-sm text-sm leading-relaxed text-ink-muted">
              A portfolio demo of an AI system that reads financial PDFs, shows its evidence and asks a
              person when something looks wrong.
            </p>
          </div>
          <div className="space-y-3 text-sm">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-ink-subtle">Explore</p>
            <ul className="space-y-2">
              <li><FooterLink href="/tour">Guided tour</FooterLink></li>
              <li><FooterLink href="/try">Try it yourself</FooterLink></li>
              <li><FooterLink href="/how-it-works">How it works</FooterLink></li>
            </ul>
          </div>
          <div className="space-y-3 text-sm">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-ink-subtle">For engineers</p>
            <ul className="space-y-2">
              <li>
                <FooterLink href={GITHUB_URL} external>
                  <span className="inline-flex items-center gap-1.5">
                    <Code2 className="size-3.5" aria-hidden /> Source code
                  </span>
                </FooterLink>
              </li>
              <li><FooterLink href="/ui/" external={false}>Engineer view</FooterLink></li>
              <li><FooterLink href="/docs" external={false}>API reference</FooterLink></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-line">
          <p className="mx-auto max-w-7xl px-4 py-5 text-xs leading-relaxed text-ink-subtle sm:px-6">
            All sample documents are synthetic. Files you upload are deleted after 24 hours. Please
            don&apos;t upload real financial documents.
          </p>
        </div>
      </footer>
    </div>
  );
}
