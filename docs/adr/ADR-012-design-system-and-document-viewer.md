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
  the original character positions. No AI is involved. The response's `positions` says where
  the boxes came from: `text_layer`, `ocr` or `none`.
- Scanned pages have no text layer. When Tesseract is configured (`DOCINTEL_OCR_PROVIDER` of
  `tesseract`, or `auto` with the binary installed, as in the Docker image), locate recognises
  the cached page render with `image_to_data`, joins the words into page text with a map back to
  each word, runs the same search, and unions the matched word boxes per printed line. The words
  are cached per page (64 pages) and dropped with the renders on purge. OCR runs outside the
  PDFium lock; a page takes roughly half a second the first time and about a millisecond after.
- Both endpoints use the same workspace scoping as the rest of the API: another visitor's
  document is a 404. PDFium isn't thread-safe, so a single lock serialises calls into it.
- The front end (`web/src/components/viewer/`) draws the boxes over the image, with a label chip,
  a keyboard-navigable list of everything boxed, page switching and zoom (up to 3x). "Zoom to the
  selected box" (or double-clicking a box) sizes the box to about half the visible width and
  centres it. "Expand" opens the same viewer in a full-screen Radix dialog with the same
  selection; Esc closes it and focus goes back to where it was. Below the `lg` breakpoint,
  "show it on the page" opens that dialog already zoomed to the box. Labels sit beside a box when
  its line has room, under a multi-line passage, and otherwise above. Fields, answer sources,
  conflicting values and the injection excerpt all link to it. The viewer is lazy-loaded (about
  17 kB gzipped) so it doesn't add to the landing page.

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

- **Boxes on scanned pages are approximate.** They come from Tesseract's word boxes, so they
  can be slightly off, and a match inside a word boxes the whole word. The viewer says "Boxes on
  scanned pages come from text recognition and may be slightly off". Where OCR isn't configured,
  scanned pages show without boxes and the viewer says "Highlighting isn't available for scanned
  pages". Textract OCR is used for extraction only; it doesn't provide viewer positions.
- **Page images aren't cached by the CDN.** They are private to a visitor's session (the cookie
  decides who may see them), so they are served with `Cache-Control: private` and CloudFront
  passes them through. That is intended, not a missed optimisation; the browser still caches them.
- **Boxes depend on the quote being findable.** If the model's quote differs from the page text
  beyond what the folded search handles, the value isn't boxed and the viewer lists it as "couldn't
  place on the page". That is the same evidence check the pipeline already makes, shown visually.
- **Rendering costs CPU on the one task.** A render takes roughly 100 to 150 ms and about 65 kB per
  page for the sample documents. The LRU and browser caching keep repeat views cheap; the existing
  per-IP request limit bounds abuse.
- **The main bundle stays under its previous size** (about 405 kB before gzip, against 443 kB
  before the redesign), because the viewer, tour, playground and how-it-works pages are separate
  chunks.
