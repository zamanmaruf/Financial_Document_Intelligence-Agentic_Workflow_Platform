import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw, ScanLine } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { api, ensureSession, type HighlightRect, type LocateQuery, type LocateResponse } from "@/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Highlight, HighlightTone } from "./highlights";

export interface DocumentViewerProps {
  documentId: string;
  pageCount: number;
  filename?: string;
  hasTextLayer?: boolean;
  highlights?: Highlight[];
  /** Controlled selection; omit to let the viewer manage it. */
  activeId?: string | null;
  onActiveChange?: (id: string | null) => void;
  /** Hide the clickable list of highlights under the toolbar. */
  hideList?: boolean;
  className?: string;
  /** Classes for the scrolling page area (set a height here). */
  pageAreaClassName?: string;
}

interface Placed {
  page: number;
  rects: HighlightRect[];
}

const ZOOMS = [1, 1.25, 1.5, 2] as const;
const A4_RATIO = 841.89 / 595.28;

const BOX: Record<HighlightTone, { idle: string; active: string; chip: string; dot: string }> = {
  brand: {
    idle: "border-[#7c6cf0]/55 bg-[#7c6cf0]/10",
    active: "border-[#6a58f0] bg-[#7c6cf0]/20 shadow-[0_0_0_3px_rgb(124_108_240/0.28)]",
    chip: "bg-[#5b4bdb] text-white",
    dot: "bg-brand",
  },
  ok: {
    idle: "border-[#0f9f68]/50 bg-[#10b981]/10",
    active: "border-[#0b8a5a] bg-[#10b981]/20 shadow-[0_0_0_3px_rgb(16_185_129/0.28)]",
    chip: "bg-[#067a50] text-white",
    dot: "bg-ok",
  },
  warn: {
    idle: "border-[#d48806]/60 bg-[#f59e0b]/12",
    active: "border-[#b77400] bg-[#f59e0b]/25 shadow-[0_0_0_3px_rgb(245_158_11/0.32)]",
    chip: "bg-[#8a5300] text-white",
    dot: "bg-warn",
  },
  danger: {
    idle: "border-[#e5484d]/70 bg-[#e5484d]/14",
    active: "border-[#d42a30] bg-[#e5484d]/22 shadow-[0_0_0_3px_rgb(229_72_77/0.32)]",
    chip: "bg-[#c4262c] text-white",
    dot: "bg-danger",
  },
};

interface LocateState {
  key: string;
  placed: Map<string, Placed[]>;
  textLayer?: boolean;
  failed?: boolean;
}

const EMPTY: Map<string, Placed[]> = new Map();

const locateCache = new Map<string, Promise<LocateResponse>>();

function cachedLocate(documentId: string, queries: LocateQuery[]): Promise<LocateResponse> {
  const key = `${documentId}|${JSON.stringify(queries)}`;
  let hit = locateCache.get(key);
  if (!hit) {
    hit = api.locate(documentId, queries);
    hit.catch(() => locateCache.delete(key));
    locateCache.set(key, hit);
  }
  return hit;
}

const TONE_ORDER: Record<HighlightTone, number> = { danger: 0, warn: 1, brand: 2, ok: 3 };

/** Problems first, so the chip that matters is never scrolled out of view. */
function orderByTone(highlights: Highlight[]): Highlight[] {
  return [...highlights].sort((a, b) => TONE_ORDER[a.tone ?? "brand"] - TONE_ORDER[b.tone ?? "brand"]);
}

function queriesFor(highlights: Highlight[]): LocateQuery[] {
  const seen = new Set<string>();
  const out: LocateQuery[] = [];
  for (const h of highlights) {
    for (const text of h.texts) {
      const key = `${h.page ?? "*"}|${text}`;
      if (!text || seen.has(key)) continue;
      seen.add(key);
      out.push({ text, page: h.page ?? null });
    }
  }
  return out.slice(0, 50);
}

/** Merge boxes on the same line that touch or overlap (union highlights overlap a lot). */
function mergeLines(rects: HighlightRect[]): HighlightRect[] {
  const sorted = [...rects].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: HighlightRect[] = [];
  for (const r of sorted) {
    const prev = out[out.length - 1];
    const sameLine = prev && Math.abs(prev.y - r.y) < Math.min(prev.height, r.height) * 0.5;
    if (prev && sameLine && r.x <= prev.x + prev.width + 0.01) {
      const right = Math.max(prev.x + prev.width, r.x + r.width);
      const bottom = Math.max(prev.y + prev.height, r.y + r.height);
      prev.y = Math.min(prev.y, r.y);
      prev.width = right - prev.x;
      prev.height = bottom - prev.y;
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

function placements(highlights: Highlight[], res: LocateResponse): Map<string, Placed[]> {
  const byKey = new Map(res.results.map((r) => [`${r.page ?? "*"}|${r.text}`, r.matches]));
  const out = new Map<string, Placed[]>();
  for (const h of highlights) {
    const pages = new Map<number, HighlightRect[]>();
    for (const text of h.texts) {
      const matches = byKey.get(`${h.page ?? "*"}|${text}`);
      if (!matches || matches.length === 0) continue;
      for (const m of matches) pages.set(m.page_number, [...(pages.get(m.page_number) ?? []), ...m.rects]);
      if (!h.union) break;
    }
    if (pages.size > 0) {
      out.set(
        h.id,
        [...pages.entries()]
          .sort(([a], [b]) => a - b)
          .map(([page, rects]) => ({ page, rects: h.union ? mergeLines(rects) : rects })),
      );
    }
  }
  return out;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export default function DocumentViewer({
  documentId,
  pageCount,
  filename,
  hasTextLayer = true,
  highlights: highlightsProp,
  activeId: activeProp,
  onActiveChange,
  hideList = false,
  className,
  pageAreaClassName,
}: DocumentViewerProps) {
  const highlights = useMemo(() => orderByTone(highlightsProp ?? []), [highlightsProp]);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState<(typeof ZOOMS)[number]>(1);
  const [ratio, setRatio] = useState(A4_RATIO);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [located, setLocated] = useState<LocateState | null>(null);
  const [innerActive, setInnerActive] = useState<string | null>(null);
  const controlled = activeProp !== undefined;
  const activeId = controlled ? activeProp : innerActive;

  const scrollRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const setActive = useCallback(
    (id: string | null) => {
      if (!controlled) setInnerActive(id);
      onActiveChange?.(id);
    },
    [controlled, onActiveChange],
  );

  const queries = useMemo(() => queriesFor(highlights), [highlights]);
  const queryKey = JSON.stringify(queries);

  useEffect(() => {
    if (queries.length === 0) return;
    let alive = true;
    cachedLocate(documentId, queries)
      .then((res) => {
        if (alive) setLocated({ key: queryKey, placed: placements(highlights, res), textLayer: res.has_text_layer });
      })
      .catch(() => {
        if (alive) setLocated({ key: queryKey, placed: new Map(), failed: true });
      });
    return () => {
      alive = false;
    };
    // queryKey captures the highlight texts; highlights' identity alone changes every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, queryKey]);

  const current = located?.key === queryKey ? located : null;
  const placed: Map<string, Placed[]> | null = queries.length === 0 ? EMPTY : (current?.placed ?? null);
  const locateFailed = current?.failed ?? false;
  const textLayer = current?.textLayer ?? hasTextLayer;

  // Selecting a highlight on another page turns to that page (state derived during render).
  const active = activeId ? placed?.get(activeId) : undefined;
  const jumpKey = `${activeId ?? ""}|${active ? active.length : -1}`;
  const [lastJump, setLastJump] = useState("");
  if (jumpKey !== lastJump) {
    setLastJump(jumpKey);
    const target = active?.[0];
    if (target && !active.some((p) => p.page === page)) setPage(target.page);
  }

  // Centre the selected highlight's first box on this page in the scroll area.
  useEffect(() => {
    const first = active?.find((p) => p.page === page)?.rects[0];
    const scroller = scrollRef.current;
    const frame = frameRef.current;
    if (!first || !scroller || !frame) return;
    const top = frame.offsetTop + first.y * frame.offsetHeight;
    const left = frame.offsetLeft + first.x * frame.offsetWidth;
    scroller.scrollTo({
      top: Math.max(0, top - scroller.clientHeight / 2),
      left: Math.max(0, left - scroller.clientWidth / 3),
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [active, page, zoom, loaded]);

  const src = `${api.pageImageUrl(documentId, page)}${retry ? `?r=${retry}` : ""}`;

  // Warm the browser cache for the other pages once the first one is on screen.
  useEffect(() => {
    if (loaded === null || pageCount > 6) return;
    for (let p = 1; p <= pageCount; p++) {
      if (p !== page) new Image().src = api.pageImageUrl(documentId, p);
    }
    // only after the first successful load of this document
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, loaded !== null]);

  const onPageBoxes = useMemo(() => {
    if (!placed) return [];
    return highlights.flatMap((h) =>
      (placed.get(h.id) ?? [])
        .filter((p) => p.page === page)
        .map((p) => ({ highlight: h, rects: p.rects })),
    );
  }, [placed, highlights, page]);

  const found = highlights.filter((h) => placed?.has(h.id));
  const missing = placed ? highlights.filter((h) => !placed.has(h.id)) : [];

  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    if (buttons.length === 0) return;
    e.preventDefault();
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next = current;
    if (e.key === "Home") next = 0;
    else if (e.key === "End") next = buttons.length - 1;
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (current + 1) % buttons.length;
    else next = (current - 1 + buttons.length) % buttons.length;
    const target = buttons[next];
    target?.focus();
    target?.click();
  };

  const zoomIndex = ZOOMS.indexOf(zoom);
  const isLoaded = loaded === src;

  return (
    <section
      aria-label={filename ? `Document viewer: ${filename}` : "Document viewer"}
      className={cn("flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-card", className)}
      data-testid="document-viewer"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex items-center gap-1" role="group" aria-label="Pages">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft />
          </Button>
          <span className="num min-w-[86px] text-center text-xs text-ink-muted" aria-live="polite">
            Page <span className="font-medium text-ink">{page}</span> of {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={page >= pageCount}
            aria-label="Next page"
          >
            <ChevronRight />
          </Button>
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Zoom">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => setZoom(ZOOMS[Math.max(0, zoomIndex - 1)] ?? 1)}
            disabled={zoomIndex <= 0}
            aria-label="Zoom out"
          >
            <Minus />
          </Button>
          <span className="num w-11 text-center text-xs text-ink-muted">{Math.round(zoom * 100)}%</span>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, zoomIndex + 1)] ?? 1)}
            disabled={zoomIndex >= ZOOMS.length - 1}
            aria-label="Zoom in"
          >
            <Plus />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2.5 text-xs"
            onClick={() => setZoom(1)}
            disabled={zoom === 1}
          >
            Fit
          </Button>
        </div>
      </div>

      {!hideList && highlights.length > 0 && (
        <div className="border-b border-line px-3 py-2">
          <div
            ref={listRef}
            role="group"
            aria-label="Highlights on the page"
            onKeyDown={onListKey}
            className="-mx-3 flex gap-1.5 overflow-x-auto px-3 pb-0.5 [mask-image:linear-gradient(to_right,black_calc(100%-28px),transparent)] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {placed === null
              ? highlights.slice(0, 4).map((h) => <span key={h.id} className="skeleton h-7 w-24 shrink-0 rounded-full" />)
              : found.map((h) => {
                  const tone = BOX[h.tone ?? "brand"];
                  const isActive = h.id === activeId;
                  return (
                    <button
                      key={h.id}
                      type="button"
                      aria-pressed={isActive}
                      tabIndex={isActive || (!activeId && h === found[0]) ? 0 : -1}
                      onClick={() => setActive(isActive ? null : h.id)}
                      className={cn(
                        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors",
                        isActive
                          ? "border-line-bright bg-surface-overlay text-ink"
                          : "border-line bg-transparent text-ink-muted hover:border-line-strong hover:text-ink",
                      )}
                    >
                      <span aria-hidden className={cn("size-1.5 rounded-full", tone.dot)} />
                      {h.label}
                      <span className="num text-ink-subtle">p.{placed.get(h.id)?.[0]?.page}</span>
                    </button>
                  );
                })}
          </div>
          {placed !== null && missing.length > 0 && textLayer && !locateFailed && (
            <p className="mt-1.5 text-xs text-ink-subtle">
              Couldn&apos;t place {missing.map((m) => m.label).join(", ")} on the page.
            </p>
          )}
        </div>
      )}

      <div
        ref={scrollRef}
        tabIndex={0}
        role="region"
        aria-label={`Page ${page} of ${pageCount}`}
        className={cn(
          "relative min-h-0 flex-1 overflow-auto bg-[#0b0c0f] p-3 sm:p-5",
          "max-h-[min(78vh,980px)]",
          pageAreaClassName,
        )}
      >
        <div
          ref={frameRef}
          className="relative mx-auto overflow-hidden rounded-[3px] bg-white shadow-[0_0_0_1px_rgb(255_255_255/0.06),0_18px_50px_-12px_rgb(0_0_0/0.8)]"
          style={{ width: `calc(min(100%, 860px) * ${zoom})`, aspectRatio: `1 / ${ratio}` }}
        >
          {!isLoaded && !imageError && <div className="skeleton absolute inset-0 rounded-none opacity-60" aria-hidden />}
          {imageError ? (
            <div className="absolute inset-0 grid place-items-center bg-surface p-6 text-center">
              <div className="space-y-3">
                <p className="text-sm text-ink">This page couldn&apos;t be shown.</p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setImageError(false);
                    void ensureSession().finally(() => setRetry((r) => r + 1));
                  }}
                >
                  <RotateCcw /> Try again
                </Button>
              </div>
            </div>
          ) : (
            <img
              key={src}
              src={src}
              alt={`Page ${page} of ${pageCount}${filename ? ` of ${filename}` : ""}`}
              className={cn(
                "absolute inset-0 size-full select-none transition-opacity duration-300",
                isLoaded ? "opacity-100" : "opacity-0",
              )}
              draggable={false}
              onLoad={(e) => {
                const img = e.currentTarget;
                if (img.naturalWidth > 0) setRatio(img.naturalHeight / img.naturalWidth);
                setLoaded(src);
              }}
              onError={() => setImageError(true)}
            />
          )}

          {isLoaded &&
            onPageBoxes.map(({ highlight, rects }) => {
              const tone = BOX[highlight.tone ?? "brand"];
              const isActive = highlight.id === activeId;
              const first = rects[0];
              const showChip = isActive || (highlight.tone === "danger" && !activeId);
              return (
                <div
                  key={`${highlight.id}-${isActive ? "on" : "off"}`}
                  aria-hidden
                  data-highlight={highlight.id}
                  data-active={isActive || undefined}
                >
                  {rects.map((r, i) => (
                    <div
                      key={i}
                      onClick={() => setActive(isActive ? null : highlight.id)}
                      className={cn(
                        "absolute cursor-pointer rounded-[3px] border-[1.5px] transition-[background-color,box-shadow,border-color] duration-200",
                        isActive ? cn(tone.active, "animate-draw") : tone.idle,
                        activeId && !isActive && "opacity-40",
                      )}
                      style={{
                        left: `${(r.x - 0.004) * 100}%`,
                        top: `${(r.y - 0.003) * 100}%`,
                        width: `${(r.width + 0.008) * 100}%`,
                        height: `${(r.height + 0.006) * 100}%`,
                        animationDelay: isActive ? `${i * 60}ms` : undefined,
                      }}
                    />
                  ))}
                  {showChip && first && (
                    <span
                      className={cn(
                        "pointer-events-none absolute z-10 animate-fade-in whitespace-nowrap rounded-[5px] px-1.5 py-0.5 text-[11px] font-semibold leading-4 shadow-md",
                        first.y > 0.04 && "-translate-y-full",
                        tone.chip,
                      )}
                      style={{
                        left: `${Math.min(first.x - 0.004, 0.62) * 100}%`,
                        top:
                          first.y > 0.04
                            ? `calc(${(first.y - 0.003) * 100}% - 4px)`
                            : `calc(${(first.y + first.height + 0.003) * 100}% + 4px)`,
                      }}
                    >
                      {highlight.label}
                      {highlight.note && <span className="font-normal opacity-90"> · {highlight.note}</span>}
                    </span>
                  )}
                </div>
              );
            })}
        </div>
      </div>

      {(!textLayer || locateFailed) && highlights.length > 0 && (
        <p className="flex items-center gap-2 border-t border-line px-3 py-2 text-xs text-ink-muted">
          <ScanLine className="size-3.5 shrink-0" aria-hidden />
          {locateFailed
            ? "Highlights couldn't be loaded right now. The page itself is still accurate."
            : "Highlighting isn't available for scanned pages."}
        </p>
      )}
    </section>
  );
}
