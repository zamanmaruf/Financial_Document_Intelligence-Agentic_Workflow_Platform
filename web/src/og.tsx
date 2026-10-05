import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { HeroFrame } from "@/components/landing/HeroFrame";
import { Logo } from "@/components/Logo";

import "@/styles/index.css";

/** The 1200x630 social card, screenshotted into public/og.png by scripts/make-og.mjs. */
function SocialCard() {
  return (
    <div className="relative flex h-[630px] w-[1200px] items-center gap-12 overflow-hidden bg-canvas px-16">
      <div aria-hidden className="bg-grid absolute inset-0" />
      <div aria-hidden className="glow-hero absolute inset-0" />
      <div className="relative w-[470px] shrink-0 space-y-7">
        <Logo className="[&_span]:text-lg [&_svg]:size-9" />
        <h1 className="text-[54px] font-semibold leading-[1.04] tracking-[-0.035em] text-ink">
          AI that reads financial PDFs, and <span className="text-gradient">shows its work.</span>
        </h1>
        <p className="text-xl leading-relaxed text-ink-muted">
          Every value boxed on the page. Refuses to guess. Asks a person when something looks wrong.
        </p>
      </div>
      <HeroFrame className="relative w-[600px] shrink-0" />
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(
  <StrictMode>
    <SocialCard />
  </StrictMode>,
);
