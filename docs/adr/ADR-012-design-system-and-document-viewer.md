# ADR-012: Design system and document viewer

- Status: Accepted
- Date: 2026-10-05

## Context

The first version of the public site ([ADR-011](ADR-011-public-demo.md)) showed results as tables:
a value, how sure the system was, and the line of text it was copied from. Visitors had to
imagine where on the page that line was. The two features that make the project interesting, a
conflict between two printed totals and a hidden instruction aimed at AI, were the hardest to see.

The redesign had two goals: a look that holds up next to well-known developer products, and a
document viewer that boxes every value, source, conflict and injected sentence on the page
itself. The constraints from ADR-011 stayed: a strict CSP (`script-src 'self'`, no inline script,
no third-party resources), document text rendered only as React text, lazy routes, keyboard
access and reduced-motion support.

## Decision

### Design system

- Dark tokens in `web/src/styles/index.css` (Tailwind v4 `@theme`): a near-black canvas, three
  surface levels, hairline borders, one violet-to-cyan accent and semantic colours tuned for
  dark backgrounds. Text colours were picked for at least 4.5:1 contrast on the canvas and
  surfaces; the axe scans in the Playwright suite enforce it.
- Geist and Geist Mono, bundled with `@fontsource-variable`, with tabular figures for numbers.
- Primitives in `web/src/components/ui/`: Button (with a loading state), Badge (status dot),
  Card, Tabs (Radix), Stepper, Kbd, Tooltip, Toast, Segmented control, Meter and Skeletons.
- Motion is short (120 to 520 ms) and decorative only; `prefers-reduced-motion` turns it off.

### Document viewer: pages rendered on the server

- `GET /documents/{id}/pages/{n}/image` renders one page to PNG with `pypdfium2` at 2x, capped at
  2,400 pixels on the long edge. Renders are kept in a 64 MB in-memory LRU and never written to
  disk, so the 24-hour retention purge is unaffected (the cache entry is dropped when a document
  is purged). Responses carry an `ETag` and `Cache-Control: private, max-age=3600`.
- `POST /documents/{id}/locate` takes up to 50 snippets (500 characters each) and returns boxes,
  normalised to 0..1 of the page, for each one. It tries an exact search on the page's text
  layer, then a folded search (case, whitespace, quotes and dashes normalised) that maps back to
  the original character positions. No AI is involved.
- Both endpoints use the same workspace scoping as the rest of the API: another visitor's
  document is a 404. PDFium isn't thread-safe, so a single lock serialises calls into it.
- The front end (`web/src/components/viewer/`) draws the boxes over the image, with a label chip,
  a keyboard-navigable list of everything boxed, page switching and zoom. Fields, answer sources,
  conflicting values and the injection excerpt all link to it. The viewer is lazy-loaded (about
  10 kB) so it doesn't add to the landing page.

### Landing page without API calls

The hero shows the real sample invoice with its boxes drawing in. The image and the box
positions come from `scripts/export_hero_assets.py`, which runs the offline engine and the
locate code once and writes `web/src/assets/hero/`. The landing page therefore creates no visitor
session and costs nothing to view.

## Alternatives considered

| Option | Why not |
|---|---|
| pdf.js in the browser | needs a worker script and `blob:` or `wasm-unsafe-eval` in the CSP; adds roughly 1 MB of JavaScript; ships a PDF parser to every visitor to parse hostile files in their browser; positions would come from a second text extractor that may not match the server's |
| Rendering every page at upload time | more disk per visitor and more to purge; most pages are never opened |
| Highlighting by fuzzy text match in the browser | the browser doesn't have character positions without a PDF parser |
| Asking the model for coordinates | slower, costs money, and can't be checked; text search on the page is exact and free |
| Keeping the light theme | the redesign brief called for a dark, premium look; the dark tokens still pass WCAG AA |

## Consequences

- **Scanned pages show without boxes.** OCR text has no positions in the PDF's text layer, so
  locate returns nothing for those pages and the viewer says "Highlighting isn't available for
  scanned pages". Adding positions from OCR output is possible later.
- **Boxes depend on the quote being findable.** If the model's quote differs from the page text
  beyond what the folded search handles, the value isn't boxed and the viewer lists it as "couldn't
  place on the page". That is the same evidence check the pipeline already makes, shown visually.
- **Rendering costs CPU on the one task.** A render takes roughly 100 to 150 ms and about 65 kB per
  page for the sample documents. The LRU and browser caching keep repeat views cheap; the existing
  per-IP request limit bounds abuse.
- **The main bundle stays under its previous size** (about 414 kB before gzip, against 443 kB
  before the redesign), because the viewer, tour, playground and how-it-works pages are separate
  chunks.
