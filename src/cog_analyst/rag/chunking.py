"""Page-aware hierarchical (parent-child) PDF chunking for the RAG corpus.

Parent-Child RAG embeds *small* passages for precise matching but feeds *larger*
passages to the LLM for fuller context:

    parent  = one full page of text (NOT embedded; returned to the LLM)
    child   = a ~150-word window within that page (embedded; used for matching)

Each child references its parent by index so the store can wire them together.
Both carry the source filename + 1-based page number for precise citations. The
only dependency, PyMuPDF, is lazy-imported.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple, Union

logger = logging.getLogger("cog_analyst.rag.chunking")

__all__ = ["ParentChunk", "ChildChunk", "chunk_pdf", "strip_boilerplate"]


@dataclass(frozen=True)
class ParentChunk:
    """A full-page passage returned to the LLM (the retrieval unit's context)."""

    source: str
    page: int
    text: str


@dataclass(frozen=True)
class ChildChunk:
    """A small embedded window; ``parent_index`` points into the parents list."""

    source: str
    page: int
    text: str
    parent_index: int


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _line_key(line: str) -> str:
    """Normalize a line for repetition counting.

    Digits and punctuation are stripped so a running footer like
    ``"Offensive and Defensive Strike 44"`` collapses to the same key on every
    page despite its changing page number.
    """
    key = re.sub(r"\d+", "", line.lower())
    return re.sub(r"[^a-z]+", " ", key).strip()


def _is_page_number(line: str) -> bool:
    """A line that is only a number (optionally 'Page 12') — a bare page number."""
    return bool(re.fullmatch(r"(?:page\s*)?\d{1,4}", line.strip().lower()))


def strip_boilerplate(
    raw_pages: Sequence[str],
    *,
    repeat_frac: float = 0.5,
    min_pages: int = 5,
    min_key_len: int = 8,
) -> List[str]:
    """Remove repeating headers/footers and bare page numbers from page texts.

    Document-agnostic: any line whose normalized key recurs on at least
    ``repeat_frac`` of pages is treated as boilerplate (running heads, footers,
    classification banners) and dropped from every page. This needs no per-PDF
    layout knowledge, so it generalizes across differently formatted sources.

    Disabled automatically for very short documents (< ``min_pages``), where
    repetition is not a reliable boilerplate signal.

    Returns one cleaned (whitespace-collapsed) text string per input page.
    """
    pages_lines = [
        [ln.strip() for ln in raw.splitlines() if ln.strip()] for raw in raw_pages
    ]
    boiler: set[str] = set()
    if len(pages_lines) >= min_pages:
        counts: Counter[str] = Counter()
        for lines in pages_lines:
            keys = {_line_key(ln) for ln in lines}
            for key in keys:
                if len(key) >= min_key_len:
                    counts[key] += 1
        threshold = max(min_pages, int(len(pages_lines) * repeat_frac))
        boiler = {key for key, count in counts.items() if count >= threshold}

    cleaned: List[str] = []
    for lines in pages_lines:
        kept = [
            ln
            for ln in lines
            if not _is_page_number(ln) and _line_key(ln) not in boiler
        ]
        cleaned.append(_clean(" ".join(kept)))
    if boiler:
        logger.info("stripped %d repeating boilerplate line(s)", len(boiler))
    return cleaned


def _window(words: List[str], size: int, overlap: int) -> Iterator[List[str]]:
    step = max(1, size - overlap)
    for start in range(0, len(words), step):
        window = words[start : start + size]
        if window:
            yield window
        if start + size >= len(words):
            break


def chunk_pdf(
    pdf_path: Union[str, Path],
    *,
    child_words: int = 150,
    child_overlap: int = 30,
    min_child_words: int = 20,
    strip_repeating: bool = True,
) -> Tuple[List[ParentChunk], List[ChildChunk]]:
    """Chunk a PDF into per-page parents and their embedded child windows.

    Parameters
    ----------
    pdf_path:
        Source PDF.
    child_words / child_overlap:
        Sliding word-window size and overlap for the embedded children.
    min_child_words:
        Drop child windows shorter than this (skips footers/near-empty pages).
        A page with no qualifying child is skipped entirely (no orphan parent).
    strip_repeating:
        Remove repeating headers/footers and bare page numbers before chunking
        (see :func:`strip_boilerplate`). On by default.

    Returns
    -------
    ``(parents, children)`` where each ``ChildChunk.parent_index`` indexes into
    ``parents``.
    """
    try:
        import fitz  # PyMuPDF, lazy import
    except ImportError as exc:  # pragma: no cover - exercised without deps
        raise ImportError(
            "RAG ingestion requires PyMuPDF. Install with: "
            "pip install 'cog-analyst[rag]'"
        ) from exc

    source = Path(pdf_path).name
    doc = fitz.open(str(pdf_path))
    parents: List[ParentChunk] = []
    children: List[ChildChunk] = []
    try:
        raw_pages = [page.get_text("text") for page in doc]
        page_texts = (
            strip_boilerplate(raw_pages)
            if strip_repeating
            else [_clean(t) for t in raw_pages]
        )
        for index, text in enumerate(page_texts):
            if not text:
                continue
            words = text.split(" ")
            page_children = [
                " ".join(w)
                for w in _window(words, child_words, child_overlap)
                if len(w) >= min_child_words
            ]
            if not page_children:
                continue
            page_no = index + 1
            parent_index = len(parents)
            parents.append(ParentChunk(source=source, page=page_no, text=text))
            for child_text in page_children:
                children.append(
                    ChildChunk(
                        source=source,
                        page=page_no,
                        text=child_text,
                        parent_index=parent_index,
                    )
                )
        logger.info(
            "chunked %s into %d parents / %d children",
            source,
            len(parents),
            len(children),
        )
    finally:
        doc.close()
    return parents, children
