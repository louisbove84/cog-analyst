"""Stateful scraper for the PLA air OOB Wikipedia markdown export.

The source is a single Markdown file (a saved Chinese Wikipedia article). Its
data lives in GFM tables, one per section, with a consistent *header* —
``航空兵部队 | 驻地 | 战术编号 | 机型 | 备注`` (unit | garrison | tactical code |
aircraft | remarks) — but inconsistent *column usage*: the UAV and carrier tables
drift, putting aircraft or theater text in the "wrong" column. So cells are
classified by **content**, not position, which is deterministic and resilient.

Two kinds of context are not in the rows themselves and are tracked as headings
stream past (a stateful pass, like the WEG scraper):

    ## 空军 / 海军 / 院校训练部队   -> service (PLAAF / PLANAF / Training)
    #### 歼击机部队 / 无人机部队 ... -> role   (fighter / uav / ...)
    ##### 东部战区空军 ...           -> theater (Eastern / ... )

A table is only parsed when its header's first cell is a known unit-table header,
so the trailing tail-number decoder matrix (header ``备注 | 0 | 1 | ...``) is
skipped automatically.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from cog_analyst.ingestion.designator import (
    DesignatorParts,
    is_designator,
    normalize_designator,
    split_aircraft_cell,
)

logger = logging.getLogger("cog_analyst.oob_markdown")

__all__ = ["UnitRecord", "parse_markdown", "normalize_designator"]

_UNIT_TABLE_HEADERS = {"航空兵部队", "航空兵部隊"}

_SERVICE_MAP = [
    ("空军", "PLAAF"),
    ("海军", "PLANAF"),
    ("院校训练部队", "Training"),
]

_ROLE_MAP = [
    ("歼击机", "fighter"),
    ("轰炸机", "bomber"),
    ("运输机", "transport"),
    ("特种机", "special_mission"),
    ("无人机", "uav"),
    ("舰载机", "carrier_based"),
    ("陆基航空兵", "land_based"),
    ("海军陆战队", "marine"),
    ("直属单位", "direct"),
]

_THEATER_MAP = [
    ("东部", "Eastern"),
    ("南部", "Southern"),
    ("西部", "Western"),
    ("北部", "Northern"),
    ("中部", "Central"),
]

_TACTICAL_CODE = re.compile(r"^[0-9][0-9A-Za-zX]{2,6}$")
_GEO_MARKERS = (
    "省",
    "市",
    "县",
    "区",
    "机场",
    "機場",
    "场站",
    "州",
    "镇",
    "村",
    "旗",
)
_AIRBASE = re.compile(r"([\u4e00-\u9fff]+?(?:机场|機場|场站))")
_ADMIN_SPLIT = re.compile(r"(?<=[省市县区州盟旗])")
_FACILITY_SUFFIX = ("机场", "機場", "场站")
_PROVINCE = re.compile(r"^([\u4e00-\u9fff]{2,4}?(?:省|自治区|直辖市))")
_WIKILINK = re.compile(r"\[([^\]]*?)\]\([^)]*\)")
_FOOTNOTE = re.compile(r"\\?\[(?:註|注|编辑)[^\]]*\\?\]")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


@dataclass
class UnitRecord:
    """One parsed OOB unit: relational fields plus normalized aircraft links."""

    unit_name: str
    service: Optional[str]
    branch: Optional[str]
    role: Optional[str]
    theater_command: Optional[str]
    location_text: Optional[str]
    province: Optional[str]
    airbase: Optional[str]
    tactical_code: Optional[str]
    remarks: Optional[str]
    source_url: Optional[str]
    aircraft: List[DesignatorParts] = field(default_factory=list)

    @property
    def unit_key(self) -> str:
        """Stable natural key: the unit name, or a synthesized fallback.

        A few rows (e.g. carrier air wings) carry no unit name; for those we
        synthesize a key from role + location so re-ingest stays idempotent.
        """
        if self.unit_name:
            return self.unit_name
        return f"{self.role or 'unit'}|{self.location_text or '?'}"


def _clean(cell: str) -> str:
    """Strip Markdown link syntax, footnote markers, and whitespace from a cell."""
    text = _WIKILINK.sub(r"\1", cell)
    text = _FOOTNOTE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _aircraft_in_cell(cell: str) -> List[DesignatorParts]:
    """Return the real aircraft designators in a cell (empty if none).

    A cell counts as aircraft only if at least one comma-split token actually
    resolves to a designator, which excludes division/unit names that merely
    contain a role character (e.g. ``运输机师``). Non-designator tokens inside a
    mixed cell are dropped so they never pollute the aircraft list.
    """
    return [part for part in split_aircraft_cell(cell) if is_designator(part.raw)]


def _extract_airbase(location: str) -> Optional[str]:
    """Pull the trailing facility name (e.g. ``湾里机场``) from a garrison string.

    Splits off administrative-division prefixes (province/city/county) and keeps
    the last segment when it names an airfield/station; otherwise falls back to
    the longest facility match anywhere in the string.
    """
    last = _ADMIN_SPLIT.split(location)[-1].strip()
    if last.endswith(_FACILITY_SUFFIX):
        return last
    matches = _AIRBASE.findall(location)
    return matches[-1] if matches else None


def _theater_label(text: str) -> Optional[str]:
    if "战区" not in text:
        return None
    for cn, label in _THEATER_MAP:
        if cn in text:
            return label
    return None


def _split_row(line: str) -> List[str]:
    """Split a GFM table row into cleaned cells (outer pipes stripped)."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [_clean(cell) for cell in inner.split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    non_empty = [c for c in cells if c]
    return bool(non_empty) and all(_SEPARATOR_CELL.match(c) for c in non_empty)


class _Context:
    """Heading state carried across rows during the single pass."""

    def __init__(self) -> None:
        self.service: Optional[str] = None
        self.branch: Optional[str] = None
        self.role: Optional[str] = None
        self.theater: Optional[str] = None

    def update(self, level: int, text: str) -> None:
        if level == 2:
            self.service = self._match(text, _SERVICE_MAP)
            self.branch = None
            self.role = None
            self.theater = None
        elif level == 3:
            self.branch = text
            self.role = self._role_or_academy(text)
            self.theater = None
        elif level == 4:
            self.role = self._role_or_academy(text)
            self.theater = None
        elif level == 5:
            self.theater = _theater_label(text)

    @staticmethod
    def _match(text: str, table: List) -> Optional[str]:
        for cn, value in table:
            if cn in text:
                return value
        return None

    def _role_or_academy(self, text: str) -> Optional[str]:
        role = self._match(text, _ROLE_MAP)
        if role is not None:
            return role
        if self.service == "Training" or "学院" in text or "大学" in text:
            return "academy"
        return None


def _build_record(cells: List[str], ctx: _Context, source_url: str) -> UnitRecord:
    """Classify a data row's cells by content into a :class:`UnitRecord`."""
    unit_name = cells[0] if cells else ""
    location_text: Optional[str] = None
    tactical_code: Optional[str] = None
    theater: Optional[str] = ctx.theater
    remarks_parts: List[str] = []
    aircraft: List[DesignatorParts] = []

    for cell in cells[1:]:
        if not cell:
            continue
        cell_aircraft = _aircraft_in_cell(cell)
        if cell_aircraft:
            aircraft.extend(cell_aircraft)
            continue
        if _TACTICAL_CODE.match(cell):
            tactical_code = cell
            continue
        theater_label = _theater_label(cell)
        if theater_label is not None:
            theater = theater_label
            remarks_parts.append(cell)
            continue
        if location_text is None and any(m in cell for m in _GEO_MARKERS):
            location_text = cell
            continue
        remarks_parts.append(cell)

    province = None
    airbase = None
    if location_text:
        province_match = _PROVINCE.match(location_text)
        province = province_match.group(1) if province_match else None
        airbase = _extract_airbase(location_text)

    return UnitRecord(
        unit_name=unit_name,
        service=ctx.service,
        branch=ctx.branch,
        role=ctx.role,
        theater_command=theater,
        location_text=location_text,
        province=province,
        airbase=airbase,
        tactical_code=tactical_code,
        remarks="; ".join(remarks_parts) or None,
        source_url=source_url,
        aircraft=aircraft,
    )


def _extract_source_url(text: str) -> str:
    """Pull the ``Source URL:`` header the export prepends, else empty string."""
    match = re.search(r"^Source URL:\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def parse_markdown(
    md_path: Union[str, Path],
    *,
    require_aircraft: bool = True,
) -> Iterator[UnitRecord]:
    """Stream :class:`UnitRecord` objects from the OOB Markdown export.

    Parameters
    ----------
    md_path:
        Path to the saved Markdown article.
    require_aircraft:
        When ``True`` (default), skip rows with no recognized aircraft — these are
        almost always staff/headquarters rows with no air assets, which add noise
        to a force-laydown corpus.
    """
    text = Path(md_path).read_text(encoding="utf-8")
    source_url = _extract_source_url(text)
    ctx = _Context()
    in_unit_table = False
    emitted = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        heading = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading is not None:
            ctx.update(len(heading.group(1)), _clean(heading.group(2)))
            in_unit_table = False
            continue

        if not line.lstrip().startswith("|"):
            continue

        cells = _split_row(line)
        if _is_separator_row(cells):
            continue

        first = cells[0] if cells else ""
        if first in _UNIT_TABLE_HEADERS:
            in_unit_table = True
            continue
        if not in_unit_table:
            continue
        # A second header-like row or an empty leading cell with no data: skip.
        if not any(cells):
            continue

        record = _build_record(cells, ctx, source_url)
        if require_aircraft and not record.aircraft:
            continue
        if not record.unit_name and not record.aircraft:
            continue
        emitted += 1
        yield record

    logger.info("parsed %d OOB units", emitted)
