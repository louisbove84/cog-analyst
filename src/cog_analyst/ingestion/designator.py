"""Deterministic crosswalk from Chinese aircraft designators to Latin ones.

PLA designators encode the role in a leading character (歼 = fighter, 轰 =
bomber, ...) followed by a number and optional variant letters. WEG and most
English sources use the transliterated Latin prefix (J-20, H-6, ...). This module
maps one to the other with a fixed, ordered prefix table — no fuzzy matching, no
model. The resulting ``en_designator`` is the join key into ``data/weg.db``.

Order matters: multi-character prefixes (歼轰, 运油) must be tested before their
single-character substrings (歼, 运), so the table is consulted longest-first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "DesignatorParts",
    "normalize_designator",
    "split_aircraft_cell",
    "is_designator",
]

# (Chinese prefix, Latin prefix). Consulted in order; longer prefixes first so a
# compound like 歼轰 is not shadowed by 歼.
_PREFIX_MAP: List[Tuple[str, str]] = [
    ("歼轰", "JH"),  # fighter-bomber
    ("运油", "YY"),  # tanker (transport-derived)
    ("空警", "KJ"),  # AEW&C
    ("无侦", "WZ"),  # reconnaissance UAV
    ("高新", "GX"),  # special-mission (High New) series
    ("攻击", "GJ"),  # attack UAV
    ("教练", "JL"),  # trainer
    ("歼", "J"),  # fighter
    ("轰", "H"),  # bomber
    ("运", "Y"),  # transport
    ("直", "Z"),  # helicopter
    ("强", "Q"),  # ground-attack
    ("教", "JL"),  # trainer (short form)
    ("苏", "Su"),  # Sukhoi (Russian origin)
    ("米", "Mi"),  # Mil helicopter (Russian origin)
    ("图", "Tu"),  # Tupolev (Russian origin)
]

# Named systems with no numeric designator in the source text.
_NAMED_MAP: List[Tuple[str, str]] = [
    ("云影", "Cloud Shadow"),
    ("翔龙", "Soaring Dragon"),
    ("神雕", "Divine Eagle"),
    ("利剑", "Sharp Sword"),
]

# A Chinese prefix (greedy) optionally separated from a leading number group.
_PREFIX_NUM = re.compile(r"^([\u4e00-\u9fff]+)[-\uff0d\u2013]?(\d+)")


@dataclass(frozen=True)
class DesignatorParts:
    """One aircraft designator in three forms.

    ``raw`` is the source token verbatim (variants kept, e.g. ``歼-10A/B/C/S``).
    ``cn_base`` is the canonical Chinese base (``歼-10``), variants stripped.
    ``en_base`` is the Latin join key (``J-10``), or ``None`` if unrecognized.
    """

    raw: str
    cn_base: str
    en_base: Optional[str]


def normalize_designator(token: str) -> DesignatorParts:
    """Map one designator token to its canonical Chinese and Latin base forms.

    Unrecognized tokens round-trip with ``en_base=None`` and ``cn_base`` set to
    the cleaned token, so nothing is silently dropped.
    """
    raw = token.strip()
    for cn_name, en_name in _NAMED_MAP:
        if raw.startswith(cn_name):
            return DesignatorParts(raw=raw, cn_base=cn_name, en_base=en_name)

    match = _PREFIX_NUM.match(raw)
    if match is None:
        return DesignatorParts(raw=raw, cn_base=raw, en_base=None)

    prefix, number = match.group(1), match.group(2)
    for cn_prefix, en_prefix in _PREFIX_MAP:
        if prefix.startswith(cn_prefix):
            return DesignatorParts(
                raw=raw,
                cn_base=f"{cn_prefix}-{number}",
                en_base=f"{en_prefix}-{number}",
            )
    return DesignatorParts(raw=raw, cn_base=raw, en_base=None)


def is_designator(token: str) -> bool:
    """True if a token resolves to a known aircraft designator.

    This is the discriminator that keeps division/unit names out of the aircraft
    list: a real designator starts with a known role prefix and (for numbered
    types) a number — e.g. ``歼-20`` parses, but ``第34运输机师`` (a division name
    that merely *contains* 运) does not.
    """
    return normalize_designator(token).en_base is not None


def split_aircraft_cell(cell: str) -> List[DesignatorParts]:
    """Split a ``机型`` cell into individual, normalized designators.

    Tokens are separated by the ideographic comma ``、``, full-width/ASCII commas,
    or ``和``. A trailing ``/`` variant list on a single type (``歼-10A/B/C/S``) is
    *kept together* as one token, so only top-level separators split.
    """
    parts: List[DesignatorParts] = []
    seen: set = set()
    for chunk in re.split(r"[\u3001\uff0c,]|和", cell):
        token = chunk.strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        parts.append(normalize_designator(token))
    return parts
