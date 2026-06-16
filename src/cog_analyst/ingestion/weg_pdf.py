"""Stateful layout-stream scraper for the ODIN WEG-style export PDF.

The document has no machine-readable structure beyond typography, but its
typography is consistent, so a single deterministic chronological pass can
reconstruct each asset:

    16.0pt  -> asset title          (record boundary; UNIQUE identity)
    12.0pt  -> section heading       (top-level JSON key)
    9.4pt   -> sub-section heading   (nested JSON key)
    8.0pt   -> body / "Label: value" (text values, parsed to key/value pairs)

Page furniture (``For Training Use Only``, ``Exported (UTC) @ ...``, page
numbers) repeats on every page and is discarded. The scraper is stateful: the
current section/sub-section carries across page breaks so a section that spills
onto the next page keeps accumulating into the same JSON key.

``fitz`` (PyMuPDF) is imported lazily so importing this module needs no PDF deps.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger("cog_analyst.weg_pdf")

# Typography thresholds (points). Noise is removed *before* size classification.
TITLE_MIN_SIZE = 14.0
SECTION_MIN_SIZE = 11.0
SUBSECTION_MIN_SIZE = 9.0

# Layout keys.
NOTES_SECTION = "Notes"  # routed to the relational `notes` column
METADATA_KEY = "Metadata"  # pre-section header block (Domain/Origin/Tiers/...)
URL_LABEL = "WEG Location"  # routed to the relational `source_url` column
TEXT_KEY = "_text"  # free-text (non key/value) lines within a container

_NOISE_PATTERNS = [
    re.compile(r"^For Training Use Only$"),
    re.compile(r"^Exported \(UTC\) @"),
]
_PAGE_NUMBER = re.compile(r"^\d{1,5}$")


@dataclass
class Line:
    """One reconstructed text line (spans joined) with its dominant typography."""

    text: str
    size: float
    font: str


@dataclass
class AssetRecord:
    """A parsed asset: relational core fields plus the dynamic JSON payload."""

    asset_title: str
    source_url: Optional[str]
    notes: Optional[str]
    payload: Dict[str, Any]

    def to_row(self) -> Tuple[str, Optional[str], Optional[str], str]:
        """Flatten to the persistence tuple, JSON-encoding the payload."""
        return (
            self.asset_title,
            self.source_url,
            self.notes,
            json.dumps(self.payload, ensure_ascii=False),
        )


def _iter_lines(doc) -> Iterator[Line]:
    """Yield reconstructed lines across the whole document in reading order."""
    for page in doc:
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                if not spans:
                    continue
                text = re.sub(r"\s+", " ", " ".join(s["text"] for s in spans)).strip()
                if not text:
                    continue
                dominant = max(spans, key=lambda s: s["size"])
                yield Line(
                    text=text, size=round(dominant["size"], 1), font=dominant["font"]
                )


def _is_noise(line: Line) -> bool:
    for pattern in _NOISE_PATTERNS:
        if pattern.match(line.text):
            return True
    # Page numbers render in Helvetica; bare digits elsewhere are real values.
    if _PAGE_NUMBER.match(line.text) and "Helvetica" in line.font:
        return True
    return False


def _classify(line: Line) -> str:
    if line.size >= TITLE_MIN_SIZE:
        return "title"
    if line.size >= SECTION_MIN_SIZE:
        return "section"
    if line.size >= SUBSECTION_MIN_SIZE:
        return "subsection"
    return "body"


def _parse_kv(text: str) -> Optional[Tuple[str, str]]:
    """Parse a ``Label: value`` line into a key/value pair.

    Structure is preserved regardless of label length: a long, descriptive label
    (e.g. a full engine specification) is still captured as a key/value pair. The
    split is on the first ``": "`` so labels keep their order and values may
    themselves contain colons (e.g. URLs). Only lines with no ``": "`` delimiter,
    or an empty key/value, fall back to free text. The relational ``Notes`` prose
    is exempted by the caller, so this never shreds the descriptive paragraph.
    """
    if ": " not in text:
        return None
    key, value = text.split(": ", 1)
    key, value = key.strip(), value.strip()
    if not key or not value:
        return None
    return key, value


def _put(container: Dict[str, Any], key: str, value: str) -> None:
    """Insert key/value, promoting to a list if the key repeats."""
    if key in container:
        existing = container[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            container[key] = [existing, value]
    else:
        container[key] = value


def _join_text(container: Dict[str, Any]) -> None:
    """Collapse accumulated ``_text`` line lists into single strings, recursively."""
    for key, value in list(container.items()):
        if key == TEXT_KEY and isinstance(value, list):
            container[key] = " ".join(value)
        elif isinstance(value, dict):
            _join_text(value)


class _AssetBuilder:
    """Accumulates one asset's content as the scraper streams its lines."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.header: Dict[str, Any] = {}
        self.sections: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._section: Optional[str] = None
        self._subsection: Optional[str] = None
        self.has_content = False

    def append_title(self, text: str) -> None:
        self.title = f"{self.title} {text}".strip()

    def start_section(self, name: str) -> None:
        self.has_content = True
        self._section = name
        self._subsection = None
        self.sections.setdefault(name, {})

    def start_subsection(self, name: str) -> None:
        self.has_content = True
        if self._section is None:
            self.start_section("General")
        assert self._section is not None
        self.sections[self._section].setdefault(name, {})
        self._subsection = name

    def add_body(self, text: str) -> None:
        self.has_content = True
        container = self._target()
        # Notes prose is routed verbatim to the notes column; do not field-parse it.
        kv = None if self._section == NOTES_SECTION else _parse_kv(text)
        if kv is not None:
            _put(container, kv[0], kv[1])
        else:
            container.setdefault(TEXT_KEY, []).append(text)

    def _target(self) -> Dict[str, Any]:
        if self._section is None:
            return self.header
        if self._subsection is None:
            return self.sections[self._section]
        return self.sections[self._section][self._subsection]

    def finalize(self) -> AssetRecord:
        source_url = self.header.pop(URL_LABEL, None)
        if isinstance(source_url, list):  # defensive: keep the first if duplicated
            source_url = source_url[0]
        _join_text(self.header)

        notes: Optional[str] = None
        notes_section = self.sections.pop(NOTES_SECTION, None)
        if notes_section is not None:
            text_value = notes_section.get(TEXT_KEY)
            if isinstance(text_value, list):
                notes = " ".join(text_value)
            elif isinstance(text_value, str):
                notes = text_value

        payload: Dict[str, Any] = {}
        if self.header:
            payload[METADATA_KEY] = self.header
        for name, body in self.sections.items():
            _join_text(body)
            payload[name] = body

        return AssetRecord(
            asset_title=self.title.strip(),
            source_url=source_url,
            notes=notes,
            payload=payload,
        )


def parse_document(
    pdf_path: Union[str, Path],
    *,
    limit: Optional[int] = None,
    log_every: int = 1000,
) -> Iterator[AssetRecord]:
    """Stream :class:`AssetRecord` objects from a WEG-style export PDF.

    Parameters
    ----------
    pdf_path:
        Path to the source PDF.
    limit:
        Stop after yielding this many assets (useful for sampling a huge file).
    log_every:
        Emit a progress log line every N assets.
    """
    try:
        import fitz  # PyMuPDF, lazy import
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise ImportError(
            "WEG PDF ingestion requires PyMuPDF. Install it with: "
            "pip install 'cog-analyst[pdf]'"
        ) from exc

    doc = fitz.open(str(pdf_path))
    try:
        builder: Optional[_AssetBuilder] = None
        emitted = 0
        for line in _iter_lines(doc):
            if _is_noise(line):
                continue
            kind = _classify(line)

            if kind == "title":
                if builder is not None and not builder.has_content:
                    # A wrapped title spanning multiple 16pt lines.
                    builder.append_title(line.text)
                    continue
                if builder is not None:
                    yield builder.finalize()
                    emitted += 1
                    if log_every and emitted % log_every == 0:
                        logger.info("parsed %d assets", emitted)
                    if limit is not None and emitted >= limit:
                        return
                builder = _AssetBuilder(line.text)
                continue

            if builder is None:
                continue  # content before the first title (front matter)
            if kind == "section":
                builder.start_section(line.text)
            elif kind == "subsection":
                builder.start_subsection(line.text)
            else:
                builder.add_body(line.text)

        if builder is not None and (limit is None or emitted < limit):
            yield builder.finalize()
    finally:
        doc.close()
