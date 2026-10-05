import { CheckCircle2, Quote } from "lucide-react";
import { useEffect, useState } from "react";

import hero from "@/assets/hero/invoice.json";
import heroPng from "@/assets/hero/invoice.png";
import { fieldLabel, formatValue } from "@/lib/plain";
import { cn } from "@/lib/utils";

/** All of the sample invoice's text sits in the top-left of the page; show just that region. */
const CROP = { x: 0.045, y: 0.025, width: 0.66, height: 0.385 };
const CYCLE_MS = 2600;

interface HeroField {
  name: string;
  value: string | number | null;
  snippet: string | null;
  rects: { x: number; y: number; width: number; height: number }[];
}

const FIELDS = hero.fields as HeroField[];
const PAGE_RATIO = hero.height / hero.width;

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The real sample invoice with the boxes the offline engine produced for it
 * (exported by scripts/export_hero_assets.py). Decorative: no API calls.
 */
export function HeroFrame({ className }: { className?: string }) {
  const [active, setActive] = useState(FIELDS.length - 1);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused || reducedMotion()) return;
    const id = window.setInterval(() => setActive((i) => (i + 1) % FIELDS.length), CYCLE_MS);
    return () => window.clearInterval(id);
  }, [paused]);

  const current = FIELDS[active];

  return (
    <figure className={cn("relative", className)}>
      <figcaption className="sr-only">
        Example output: the sample invoice from Acme Office Supplies with its {FIELDS.length} extracted
        values boxed on the page where they were found.
      </figcaption>
      <div aria-hidden className="absolute -inset-px rounded-[22px] ring-gradient opacity-80" />
      <div
        aria-hidden
        className="relative overflow-hidden rounded-[22px] border border-line bg-surface/90 shadow-float backdrop-blur"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <span className="flex gap-1.5">
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
          </span>
          <span className="truncate font-mono text-xs text-ink-muted">{hero.source}</span>
          <span className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-ok-line bg-ok-soft px-2 py-0.5 text-[11px] font-medium text-ok">
            <CheckCircle2 className="size-3" /> Ready: all checks passed
          </span>
        </div>

        <div className="grid gap-0 sm:grid-cols-[1.25fr_1fr]">
          <div className="border-b border-line bg-[#0b0c0f] p-3 sm:border-b-0 sm:border-r sm:p-4">
            <div
              className="relative overflow-hidden rounded-md bg-white shadow-[0_12px_40px_-12px_rgb(0_0_0/0.8)]"
              style={{ aspectRatio: `${CROP.width} / ${PAGE_RATIO * CROP.height}` }}
            >
              <div
                className="absolute"
                style={{
                  width: `${100 / CROP.width}%`,
                  left: `${(-CROP.x / CROP.width) * 100}%`,
                  top: `${(-CROP.y / CROP.height) * 100}%`,
                  aspectRatio: `1 / ${PAGE_RATIO}`,
                }}
              >
                <img src={heroPng} alt="" className="absolute inset-0 size-full" draggable={false} />
                {FIELDS.map((f, i) =>
                  f.rects.map((r, j) => (
                    <div
                      key={`${f.name}-${j}`}
                      onMouseEnter={() => setActive(i)}
                      className={cn(
                        "absolute animate-draw rounded-[3px] border-[1.5px] transition-[background-color,border-color,box-shadow,opacity] duration-300",
                        i === active
                          ? "border-[#6a58f0] bg-[#7c6cf0]/20 shadow-[0_0_0_3px_rgb(124_108_240/0.25)]"
                          : "border-[#0f9f68]/45 bg-[#10b981]/8 opacity-80",
                      )}
                      style={{
                        left: `${(r.x - 0.006) * 100}%`,
                        top: `${(r.y - 0.004) * 100}%`,
                        width: `${(r.width + 0.012) * 100}%`,
                        height: `${(r.height + 0.008) * 100}%`,
                        animationDelay: `${300 + i * 140}ms`,
                      }}
                    />
                  )),
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-col">
            <ul className="flex-1 divide-y divide-line">
              {FIELDS.map((f, i) => (
                <li
                  key={f.name}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "relative flex animate-fade-in items-baseline justify-between gap-3 px-4 py-2 text-[13px] transition-colors",
                    i === active ? "bg-white/[0.04]" : "",
                  )}
                  style={{ animationDelay: `${200 + i * 90}ms` }}
                >
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-brand to-brand-2 transition-opacity duration-300",
                      i === active ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="text-ink-muted">{fieldLabel(f.name)}</span>
                  <span className="num truncate font-medium text-ink">{formatValue(f.name, f.value)}</span>
                </li>
              ))}
            </ul>
            {current?.snippet && (
              <div key={current.name} className="m-3 mt-0 animate-fade-in rounded-lg border border-brand-line bg-brand-soft px-3 py-2">
                <p className="flex items-center gap-1.5 text-[11px] font-medium text-brand">
                  <Quote className="size-3" /> Found on page 1 · confirmed in the document
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-ink">{current.snippet}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </figure>
  );
}
