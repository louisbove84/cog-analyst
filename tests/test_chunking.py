"""Tests for boilerplate stripping in RAG chunking (offline, no PDF needed)."""

from __future__ import annotations

from cog_analyst.rag.chunking import strip_boilerplate

# A running header + footer that repeat on every page, plus a bare page number.
HEADER = "OFFICE OF THE SECRETARY OF DEFENSE Annual Report to Congress"
FOOTER = "Offensive and Defensive Strike"

# Distinct body sentences (differ by real words, not just a number — lines that
# differ only by digits are intentionally treated as repeating footers).
BODIES = [
    "the rocket force fields ballistic missiles",
    "naval aviation expands carrier operations",
    "logistics support centers were reorganized",
    "fighter modernization continues with stealth aircraft",
    "early warning radars cover the strait",
    "amphibious forces rehearse joint landings",
    "air defense networks integrate sam batteries",
    "space assets enable long range targeting",
]


def _page(n: int, body: str) -> str:
    return f"{HEADER}\n{body}\n{FOOTER} {n}\n{n}"


# TLDR: Repeating header/footer lines are removed; unique body text survives.
def test_strips_repeating_header_and_footer():
    pages = [_page(i, body) for i, body in enumerate(BODIES, start=1)]
    cleaned = strip_boilerplate(pages)
    for body, text in zip(BODIES, cleaned):
        assert HEADER not in text
        assert FOOTER not in text
        assert body in text


# TLDR: A bare page-number line is dropped even when it is not repeated text.
def test_strips_bare_page_numbers():
    pages = [_page(i, body) for i, body in enumerate(BODIES, start=1)]
    cleaned = strip_boilerplate(pages)
    for i, text in enumerate(cleaned, start=1):
        assert not text.strip().endswith(f" {i}")


# TLDR: Short documents are left intact (repetition isn't a reliable signal).
def test_short_doc_not_stripped():
    pages = [_page(1, BODIES[0]), _page(2, BODIES[1])]
    cleaned = strip_boilerplate(pages)
    assert any(HEADER in text for text in cleaned)


# TLDR: Genuinely unique body lines are never treated as boilerplate.
def test_unique_lines_preserved():
    pages = [f"{HEADER}\n{body}\n{i}" for i, body in enumerate(BODIES, start=1)]
    cleaned = strip_boilerplate(pages)
    for body, text in zip(BODIES, cleaned):
        assert body in text
