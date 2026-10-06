import type { Citation, Entity, HighlightRect } from "@/api/client";
import { fieldLabel, formatValue } from "@/lib/plain";

export type HighlightTone = "brand" | "ok" | "warn" | "danger";

/** Something to box on the page. ``texts`` are candidates; the first one found wins. */
export interface Highlight {
  id: string;
  label: string;
  texts: string[];
  page?: number | null;
  tone?: HighlightTone;
  /** Shown next to the box, e.g. why it matters. */
  note?: string;
  /** Box every text that is found (merged per line) instead of only the first. */
  union?: boolean;
}

const MAX_QUERY_CHARS = 500;
const MASK = /\*{4}\d{2,}/;
const MIN_PIECE_CHARS = 12;

/** Trim long passages to a searchable opening on a word boundary. */
export function searchable(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return (space > max * 0.6 ? cut.slice(0, space) : cut).slice(0, MAX_QUERY_CHARS);
}

/** One box per printed line: union highlights are overlapping fragments of the same passage. */
export function mergeLines(rects: HighlightRect[]): HighlightRect[] {
  const sorted = [...rects].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: HighlightRect[] = [];
  for (const r of sorted) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.y - r.y) < Math.min(prev.height, r.height) * 0.5) {
      const left = Math.min(prev.x, r.x);
      const top = Math.min(prev.y, r.y);
      const right = Math.max(prev.x + prev.width, r.x + r.width);
      const bottom = Math.max(prev.y + prev.height, r.y + r.height);
      Object.assign(prev, { x: left, y: top, width: right - left, height: bottom - top });
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

export interface ChipPlacement {
  /** right: vertically centred just after the box; above/below: aligned with its left edge. */
  side: "right" | "above" | "below";
  left: number;
  /** For "right", the box's vertical centre; otherwise the edge the chip sits against. */
  top: number;
  maxWidth: number;
}

const CHIP_GAP = 0.008;

/**
 * Where a highlight's label goes, in page fractions, given its boxes in reading order. Beside
 * the first line when there is room (a label above would cover the line before); under the last
 * line of a passage, which usually ends a paragraph; otherwise above, or below near the top edge.
 */
export function chipPlacement(rects: HighlightRect[]): ChipPlacement | null {
  const first = rects[0];
  const last = rects[rects.length - 1];
  if (!first || !last) return null;
  const right = first.x + first.width;
  if (right < 0.7) {
    const left = right + CHIP_GAP;
    return { side: "right", left, top: first.y + first.height / 2, maxWidth: 1 - left - 0.01 };
  }
  const left = Math.max(0.005, Math.min(first.x - 0.004, 0.62));
  const maxWidth = 1 - left - 0.01;
  const below = { side: "below", left, maxWidth } as const;
  if (rects.length > 1 && last.y + last.height < 0.96) return { ...below, top: last.y + last.height + 0.003 };
  if (first.y > 0.04) return { side: "above", left, top: first.y - 0.003, maxWidth };
  return { ...below, top: first.y + first.height + 0.003 };
}

export const fieldHighlightId = (name: string) => `field:${name}`;
export const citationHighlightId = (answerId: string, index: number) => `cite:${answerId}:${index}`;
export const conflictHighlightId = (name: string, index: number) => `conflict:${name}:${index}`;
export const injectionHighlightId = (index: number) => `injection:${index}`;

function toneFor(status: Entity["validation_status"]): HighlightTone {
  if (status === "valid" || status === "corrected") return "ok";
  if (status === "invalid") return "danger";
  if (status === "missing") return "brand";
  return "warn";
}

/** Where a field's row should point in the viewer: its quote, or every competing value. */
export function fieldLocateId(e: Entity): string | null {
  if (e.alternatives?.length) return conflictHighlightId(e.name, 0);
  return e.evidence?.snippet?.trim() ? fieldHighlightId(e.name) : null;
}

/** One box per extracted field with a supporting quote; conflicting fields box every value. */
export function fieldHighlights(entities: Entity[]): Highlight[] {
  return entities.flatMap((e) => {
    if (e.alternatives?.length) return conflictHighlights(e);
    const snippet = e.evidence?.snippet?.trim();
    if (!snippet) return [];
    const texts = [searchable(snippet)];
    if (e.raw_text && e.raw_text.trim() && !snippet.includes(e.raw_text.trim())) {
      texts.push(searchable(e.raw_text));
    }
    return [
      {
        id: fieldHighlightId(e.name),
        label: fieldLabel(e.name),
        texts,
        page: e.evidence?.page_number ?? null,
        tone: toneFor(e.validation_status),
      },
    ];
  });
}

/** One box per answer source. */
export function citationHighlights(answerId: string, citations: Citation[]): Highlight[] {
  return citations.map((c, i) => ({
    id: citationHighlightId(answerId, i),
    label: `Source ${i + 1}`,
    texts: [searchable(c.text_snippet, 140), searchable(c.text_snippet, 60)],
    page: c.page_number ?? null,
    tone: "brand",
  }));
}

/** How a number is likely printed: 9,750,000 / 9,750,000.00 / 9.750.000,00. */
export function numberSpellings(value: number): string[] {
  const whole = Number.isInteger(value);
  const en = value.toLocaleString("en-US", {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  });
  const en2 = value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const eu = value.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return [...new Set([en, en2, eu])];
}

/** Every competing value of a conflicting field, each boxed wherever it appears. */
export function conflictHighlights(entity: Entity): Highlight[] {
  const values = [entity.value, ...(entity.alternatives ?? [])].filter(
    (v, i, all): v is number | string => v !== null && v !== undefined && all.indexOf(v) === i,
  );
  return values.map((v, i) => ({
    id: conflictHighlightId(entity.name, i),
    label: `${fieldLabel(entity.name)}: ${formatValue(entity.name, v)}`,
    texts: typeof v === "number" ? numberSpellings(v) : [searchable(String(v))],
    page: null,
    tone: "warn",
  }));
}

/**
 * The planted instructions the scanner flagged, as one red box. The scanner's examples are
 * overlapping windows (~20 characters of context each side), so every one found is merged.
 * Account numbers in the examples are masked (****1234), which never matches the page, so
 * the text either side of a mask is searched on its own too.
 */
export function injectionHighlights(examples: string[]): Highlight[] {
  if (examples.length === 0) return [];
  const texts = examples.flatMap((ex) => {
    const inner = ex.length > 60 ? ex.slice(20, -20) : ex;
    const pieces = MASK.test(ex)
      ? ex
          .split(MASK)
          .map((p) => p.trim())
          .filter((p) => p.length >= MIN_PIECE_CHARS)
          .map((p) => searchable(p, 300))
      : [];
    return [searchable(ex, 300), searchable(inner, 300), ...pieces];
  });
  return [
    {
      id: injectionHighlightId(0),
      label: "Instruction aimed at AI",
      note: "Ignored",
      texts: [...new Set(texts)],
      page: null,
      tone: "danger",
      union: true,
    },
  ];
}
