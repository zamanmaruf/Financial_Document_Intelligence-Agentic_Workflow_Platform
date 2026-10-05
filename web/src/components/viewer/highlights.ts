import type { Citation, Entity } from "@/api/client";
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

/** Trim long passages to a searchable opening on a word boundary. */
export function searchable(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return (space > max * 0.6 ? cut.slice(0, space) : cut).slice(0, MAX_QUERY_CHARS);
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
 */
export function injectionHighlights(examples: string[]): Highlight[] {
  if (examples.length === 0) return [];
  const texts = examples.flatMap((ex) => {
    const inner = ex.length > 60 ? ex.slice(20, -20) : ex;
    return [searchable(ex, 300), searchable(inner, 300)];
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
