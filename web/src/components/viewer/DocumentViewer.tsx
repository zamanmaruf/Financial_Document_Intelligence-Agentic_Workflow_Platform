import { ChevronLeft, ChevronRight, Focus, Maximize2, Minus, Plus, RotateCcw, ScanLine, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import { api, ensureSession, type HighlightRect, type LocateQuery, type LocateResponse } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { chipPlacement, mergeLines, type Highlight, type HighlightTone } from "./highlights";

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
  /** Controlled full-screen view; omit to let the viewer's Expand button manage it. */
  expanded?: boolean;
  onExpandedChange?: (open: boolean) => void;
  /** Rendered inside the full-screen dialog: shows Close instead of Expand. */
  inDialog?: boolean;
  initialPage?: number;
  /** Zoom to the selected box as soon as it is on screen. */
  focusOnOpen?: boolean;
}

interface Placed {
  page: number;
  rects: HighlightRect[];
}

const ZOOMS = [1, 1.25, 1.5, 2, 3] as const;
const MIN_ZOOM = ZOOMS[0];
const MAX_ZOOM = ZOOMS[ZOOMS.length - 1] ?? 3;
/** Zoom to box: the box spans this share of the visible width. */
const FOCUS_SHARE = 0.55;
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

type Positions = LocateResponse["positions"];

interface LocateState {
  key: string;
  placed: Map<string, Placed[]>;
  positions?: Positions;
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

function unionBox(rects: HighlightRect[]): HighlightRect | null {
  if (rects.length === 0) return null;
  const left = Math.min(...rects.map((r) => r.x));
  const top = Math.min(...rects.map((r) => r.y));
  const right = Math.max(...rects.map((r) => r.x + r.width));
  const bottom = Math.max(...rects.map((r) => r.y + r.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

const HIT_SLOP = 0.006;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export default function DocumentViewer(props: DocumentViewerProps) {
  const {
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
    expanded: expandedProp,
    onExpandedChange,
    inDialog = false,
    initialPage = 1,
    focusOnOpen = false,
  } = props;
  const highlights = useMemo(() => orderByTone(highlightsProp ?? []), [highlightsProp]);
  const [page, setPage] = useState(() => Math.min(Math.max(1, initialPage), Math.max(1, pageCount)));
  const [zoom, setZoom] = useState(1);
  const [focusTick, setFocusTick] = useState(0);
  const [ratio, setRatio] = useState(A4_RATIO);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [located, setLocated] = useState<LocateState | null>(null);
  const [innerActive, setInnerActive] = useState<string | null>(null);
  const [innerExpanded, setInnerExpanded] = useState(false);
  const [expandedHere, setExpandedHere] = useState(false);
  const controlled = activeProp !== undefined;
  const activeId = controlled ? activeProp : innerActive;
  const expanded = expandedProp ?? innerExpanded;

  const scrollRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const focusedOnce = useRef(false);
  // Opened from code (Expand, or a row's "show it on the page"), so there's no Radix trigger
  // to return focus to: remember what had focus instead.
  const returnFocus = useRef<HTMLElement | null>(null);

  const setActive = useCallback(
    (id: string | null) => {
      if (!controlled) setInnerActive(id);
      onActiveChange?.(id);
    },
    [controlled, onActiveChange],
  );

  const setExpanded = (open: boolean, here = false) => {
    setExpandedHere(open && here);
    if (expandedProp === undefined) setInnerExpanded(open);
    onExpandedChange?.(open);
  };

  const queries = useMemo(() => queriesFor(highlights), [highlights]);
  const queryKey = JSON.stringify(queries);

  useEffect(() => {
    if (queries.length === 0) return;
    let alive = true;
    cachedLocate(documentId, queries)
      .then((res) => {
        if (alive) setLocated({ key: queryKey, placed: placements(highlights, res), positions: res.positions });
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
  const positions: Positions | undefined = current?.positions ?? (hasTextLayer ? "text_layer" : undefined);

  // Selecting a highlight on another page turns to that page (state derived during render).
  const active = activeId ? placed?.get(activeId) : undefined;
  const jumpKey = `${activeId ?? ""}|${active ? active.length : -1}`;
  const [lastJump, setLastJump] = useState("");
  if (jumpKey !== lastJump) {
    setLastJump(jumpKey);
    const target = active?.[0];
    if (target && !active.some((p) => p.page === page)) setPage(target.page);
  }
  const activeOnPage = active?.find((p) => p.page === page)?.rects;

  // Centre the selected highlight on this page in the scroll area.
  useEffect(() => {
    const box = activeOnPage ? unionBox(activeOnPage) : null;
    const scroller = scrollRef.current;
    const frame = frameRef.current;
    if (!box || !scroller || !frame) return;
    const top = frame.offsetTop + (box.y + box.height / 2) * frame.offsetHeight;
    const left = frame.offsetLeft + (box.x + box.width / 2) * frame.offsetWidth;
    scroller.scrollTo({
      top: Math.max(0, top - scroller.clientHeight / 2),
      left: Math.max(0, left - scroller.clientWidth / 2),
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [activeOnPage, zoom, loaded, focusTick]);

  /** Zoom so the boxes span about half the visible width, then centre them. */
  const zoomTo = useCallback(
    (rects: HighlightRect[]) => {
      const box = unionBox(rects);
      const scroller = scrollRef.current;
      const frame = frameRef.current;
      if (!box || !scroller || !frame || box.width <= 0) return;
      const style = getComputedStyle(scroller);
      const visible = scroller.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const base = frame.offsetWidth / zoom;
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (FOCUS_SHARE * visible) / (box.width * base)));
      setZoom(Math.round(next * 100) / 100);
      setFocusTick((t) => t + 1);
    },
    [zoom],
  );

  const src = `${api.pageImageUrl(documentId, page)}${retry ? `?r=${retry}` : ""}`;
  const isLoaded = loaded === src;

  // Opened from "show it on the page": zoom to the box once it is drawn.
  useEffect(() => {
    if (!focusOnOpen || focusedOnce.current || !isLoaded || !activeOnPage) return;
    const id = requestAnimationFrame(() => {
      focusedOnce.current = true;
      zoomTo(activeOnPage);
    });
    return () => cancelAnimationFrame(id);
  }, [focusOnOpen, isLoaded, activeOnPage, zoomTo]);

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

  // Double-clicking a box zooms to it. The first click re-keys the boxes, so no dblclick event
  // reaches them: catch the second click on the frame and hit-test it instead.
  const onFrameClick = (e: MouseEvent<HTMLDivElement>) => {
    const frame = frameRef.current;
    if (e.detail !== 2 || !frame || !isLoaded) return;
    const r = frame.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    const inside = (b: HighlightRect) =>
      x >= b.x - HIT_SLOP && x <= b.x + b.width + HIT_SLOP && y >= b.y - HIT_SLOP && y <= b.y + b.height + HIT_SLOP;
    const hit = onPageBoxes.find(({ rects }) => rects.some(inside));
    if (!hit) return;
    setActive(hit.highlight.id);
    zoomTo(hit.rects);
  };

  const zoomOut = () => setZoom((z) => [...ZOOMS].reverse().find((v) => v < z - 0.001) ?? MIN_ZOOM);
  const zoomIn = () => setZoom((z) => ZOOMS.find((v) => v > z + 0.001) ?? MAX_ZOOM);

  const footer = locateFailed
    ? "Highlights couldn't be loaded right now. The page itself is still accurate."
    : positions === "ocr"
      ? "Boxes on scanned pages come from text recognition and may be slightly off."
      : positions === "none"
        ? "Highlighting isn't available for scanned pages."
        : null;
  const canPlace = positions === "text_layer" || positions === "ocr";

  return (
    <section
      aria-label={filename ? `Document viewer: ${filename}` : "Document viewer"}
      className={cn("flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-card", className)}
      data-testid={inDialog ? "document-viewer-expanded" : "document-viewer"}
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
          <Button variant="ghost" size="icon" className="size-8" onClick={zoomOut} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out">
            <Minus />
          </Button>
          <span className="num w-11 text-center text-xs text-ink-muted" data-testid="zoom-level">
            {Math.round(zoom * 100)}%
          </span>
          <Button variant="ghost" size="icon" className="size-8" onClick={zoomIn} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in">
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
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => activeOnPage && zoomTo(activeOnPage)}
            disabled={!activeOnPage || !isLoaded}
            aria-label="Zoom to the selected box"
            title="Zoom to the selected box (or double-click a box)"
          >
            <Focus />
          </Button>
          {inDialog ? (
            <DialogClose asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label="Close full screen" title="Close (Esc)">
                <X />
              </Button>
            </DialogClose>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={(e) => {
                // Safari doesn't focus buttons on click, so name the one to come back to
                returnFocus.current = e.currentTarget;
                setExpanded(true, true);
              }}
              aria-label="Expand to full screen"
              aria-haspopup="dialog"
              title="Expand to full screen"
            >
              <Maximize2 />
            </Button>
          )}
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
          {placed !== null && missing.length > 0 && canPlace && !locateFailed && (
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
          onClick={onFrameClick}
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
              const showChip = isActive || (highlight.tone === "danger" && !activeId);
              const chip = chipPlacement(rects);
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
                      onClick={(e) => {
                        if (e.detail < 2) setActive(isActive ? null : highlight.id);
                      }}
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
                  {showChip && chip && (
                    <span
                      data-chip={chip.side}
                      className={cn(
                        "pointer-events-none absolute z-10 animate-fade-in overflow-hidden text-ellipsis whitespace-nowrap rounded-[5px] px-1.5 py-0.5 text-[11px] font-semibold leading-4 shadow-md",
                        chip.side === "right" && "-translate-y-1/2",
                        chip.side === "above" && "-translate-y-full",
                        tone.chip,
                      )}
                      style={{
                        left: `${chip.left * 100}%`,
                        maxWidth: `${chip.maxWidth * 100}%`,
                        top:
                          chip.side === "above"
                            ? `calc(${chip.top * 100}% - 4px)`
                            : chip.side === "below"
                              ? `calc(${chip.top * 100}% + 4px)`
                              : `${chip.top * 100}%`,
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

      {footer && highlights.length > 0 && (
        <p className="flex items-center gap-2 border-t border-line px-3 py-2 text-xs text-ink-muted">
          <ScanLine className="size-3.5 shrink-0" aria-hidden />
          {footer}
        </p>
      )}

      {!inDialog && (
        <Dialog open={expanded} onOpenChange={(open) => setExpanded(open)}>
          <DialogContent
            className="inset-0 flex flex-col sm:inset-4 lg:inset-6"
            onOpenAutoFocus={() => {
              const el = document.activeElement;
              if (el instanceof HTMLElement && el !== document.body) returnFocus.current = el;
            }}
            onCloseAutoFocus={(e) => {
              const el = returnFocus.current;
              returnFocus.current = null;
              if (el?.isConnected) {
                e.preventDefault();
                el.focus();
              }
            }}
          >
            <DialogTitle className="sr-only">{filename ?? "Document"}, full screen</DialogTitle>
            <DialogDescription className="sr-only">
              The page with its highlights. Press Escape to close.
            </DialogDescription>
            {expanded && (
              <DocumentViewer
                {...props}
                activeId={activeId}
                onActiveChange={setActive}
                inDialog
                initialPage={page}
                focusOnOpen={!expandedHere}
                className="h-full rounded-none border-0 sm:rounded-xl sm:border"
                pageAreaClassName="max-h-none"
              />
            )}
          </DialogContent>
        </Dialog>
      )}
    </section>
  );
}
