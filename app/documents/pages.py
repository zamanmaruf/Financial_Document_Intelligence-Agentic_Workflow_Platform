"""Page images and text positions for the document viewer, rendered with PDFium.

Nothing is written to disk: rendered PNGs live in a byte-bounded in-memory LRU. Text positions
come from the PDF's own text layer, so scanned pages (no text layer) yield no highlights.

PDFium is not thread-safe, so every call into it is serialised behind ``PDFIUM_LOCK``.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import pypdfium2 as pdfium

from app.core.errors import DocumentNotFoundError
from app.providers.storage.local import DocumentStore

PDFIUM_LOCK = threading.Lock()

RENDER_VERSION = "1"
RENDER_SCALE = 2.0  # 144 dpi: crisp on high-density screens at the viewer's default width
MAX_RENDER_EDGE_PX = 2400
MAX_MATCHES_PER_PAGE = 10

_CHAR_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
)


@dataclass(frozen=True)
class RenderedPage:
    png: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Rect:
    """A box in page-relative coordinates: (0, 0) is the top-left corner, 1 is the full edge."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class PageMatch:
    page_number: int
    rects: list[Rect]


@dataclass(frozen=True)
class LocateQuery:
    text: str
    page: int | None = None  # None searches every page


@dataclass
class LocateOutcome:
    query: LocateQuery
    matches: list[PageMatch] = field(default_factory=list)


def fold(text: str) -> tuple[str, list[int]]:
    """Lower-case, unify quotes/dashes and collapse whitespace runs to one space.

    Returns the folded string and, for each folded character, the index of the original
    character it came from, so a match in the folded text maps back to a source range.
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text.translate(_CHAR_FOLD)):
        if ch.isspace():
            if not out or out[-1] == " ":
                continue
            out.append(" ")
        else:
            out.append(ch.lower())
        index.append(i)
    if out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def find_ranges(
    page_text: str, query: str, limit: int = MAX_MATCHES_PER_PAGE
) -> list[tuple[int, int]]:
    """Character ranges ``(start, length)`` of ``query`` in ``page_text``.

    Exact matches win; otherwise fall back to a case- and whitespace-insensitive search, which
    also matches text that wraps across a line break.
    """
    needle = query.strip()
    if not needle:
        return []
    ranges: list[tuple[int, int]] = []
    start = page_text.find(needle)
    while start >= 0 and len(ranges) < limit:
        ranges.append((start, len(needle)))
        start = page_text.find(needle, start + len(needle))
    if ranges:
        return ranges

    folded, index = fold(page_text)
    folded_needle, _ = fold(needle)
    if not folded_needle:
        return []
    pos = folded.find(folded_needle)
    while pos >= 0 and len(ranges) < limit:
        first = index[pos]
        last = index[pos + len(folded_needle) - 1]
        ranges.append((first, last - first + 1))
        pos = folded.find(folded_needle, pos + len(folded_needle))
    return ranges


def _normalise(box: tuple[float, float, float, float], width: float, height: float) -> Rect | None:
    left, bottom, right, top = box
    x0 = min(max(left / width, 0.0), 1.0)
    x1 = min(max(right / width, 0.0), 1.0)
    y0 = min(max((height - top) / height, 0.0), 1.0)
    y1 = min(max((height - bottom) / height, 0.0), 1.0)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return Rect(x=round(x0, 5), y=round(y0, 5), width=round(x1 - x0, 5), height=round(y1 - y0, 5))


class PageService:
    """Renders pages and locates text in stored PDFs."""

    def __init__(self, store: DocumentStore, cache_bytes: int = 64 * 1024 * 1024) -> None:
        self._store = store
        self._cache_bytes = cache_bytes
        self._cache: OrderedDict[tuple[str, int], RenderedPage] = OrderedDict()
        self._cached_total = 0
        self._cache_lock = threading.Lock()

    @staticmethod
    def etag(sha256: str, page_number: int) -> str:
        return f'"{sha256[:24]}-p{page_number}-r{RENDER_VERSION}"'

    def render(self, document_id: str, page_number: int) -> RenderedPage:
        key = (document_id, page_number)
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        page = self._render_uncached(document_id, page_number)
        self._remember(key, page)
        return page

    def forget(self, document_id: str) -> None:
        """Drop cached renders of a document (called when it is deleted)."""
        with self._cache_lock:
            for key in [k for k in self._cache if k[0] == document_id]:
                self._cached_total -= len(self._cache.pop(key).png)

    def locate(self, document_id: str, queries: Sequence[LocateQuery]) -> list[LocateOutcome]:
        outcomes = [LocateOutcome(query=q) for q in queries]
        data = self._store.load(document_id)
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                page_count = len(pdf)
                for page_number in self._pages_needed(queries, page_count):
                    self._locate_on_page(pdf, page_number, outcomes)
            finally:
                pdf.close()
        return outcomes

    def _render_uncached(self, document_id: str, page_number: int) -> RenderedPage:
        data = self._store.load(document_id)
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                if not 1 <= page_number <= len(pdf):
                    raise DocumentNotFoundError(f"page {page_number} not found")
                page = pdf[page_number - 1]
                try:
                    w, h = page.get_size()
                    scale = min(RENDER_SCALE, MAX_RENDER_EDGE_PX / max(w, h, 1.0))
                    image = page.render(scale=scale).to_pil()
                finally:
                    page.close()
            finally:
                pdf.close()
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return RenderedPage(png=buf.getvalue(), width=image.width, height=image.height)

    def _remember(self, key: tuple[str, int], page: RenderedPage) -> None:
        size = len(page.png)
        if size > self._cache_bytes:
            return
        with self._cache_lock:
            if key in self._cache:
                return
            self._cache[key] = page
            self._cached_total += size
            while self._cached_total > self._cache_bytes:
                _, evicted = self._cache.popitem(last=False)
                self._cached_total -= len(evicted.png)

    @staticmethod
    def _pages_needed(queries: Iterable[LocateQuery], page_count: int) -> list[int]:
        wanted: set[int] = set()
        for q in queries:
            if q.page is None:
                return list(range(1, page_count + 1))
            if 1 <= q.page <= page_count:
                wanted.add(q.page)
        return sorted(wanted)

    @staticmethod
    def _locate_on_page(
        pdf: pdfium.PdfDocument, page_number: int, outcomes: list[LocateOutcome]
    ) -> None:
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            textpage = page.get_textpage()
            try:
                n = textpage.count_chars()
                if n <= 0:
                    return  # scanned page: no text layer to position highlights with
                text = textpage.get_text_range(0, n)
                for outcome in outcomes:
                    q = outcome.query
                    if q.page is not None and q.page != page_number:
                        continue
                    rects: list[Rect] = []
                    for start, length in find_ranges(text, q.text):
                        for i in range(textpage.count_rects(start, length)):
                            rect = _normalise(textpage.get_rect(i), width, height)
                            if rect is not None:
                                rects.append(rect)
                    if rects:
                        outcome.matches.append(PageMatch(page_number=page_number, rects=rects))
            finally:
                textpage.close()
        finally:
            page.close()
