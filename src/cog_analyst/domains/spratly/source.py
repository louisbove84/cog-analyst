"""Spratly domain source provenance + bundled demo excerpts.

The demo passages are verbatim excerpts from the core source document, each
prefixed with a citation header so the extractor populates ``source_citation``
from the text rather than from memory.
"""

from __future__ import annotations

from typing import List

from cog_analyst import config

CORE_SOURCE_PDF = config.RAG_DOCS_DIR / "OffensiveDefensiveStrike.pdf"
CORE_SOURCE_CITATION = (
    "Dahm, J.M. (2021), 'Offensive and Defensive Strike,' JHU/APL South China "
    "Sea Military Capability Series, NSAD-R-21-016"
)

# Default dataset location for the Spratly slice.
SPRATLY_DB_PATH = config.DATA_DIR / "spratly_fleet.db"

DEMO_WEAPON_SNIPPETS: List[str] = [
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.6]\n"
        "The HQ-9B is the newest fielded variant in the PLA's HQ-9 SAM series. "
        "This road-mobile Chinese SAM system has four missile canisters per TEL "
        "and is based on the Russian S-300 (SA-20). While earlier versions "
        "advertised a maximum range of 200 kilometers, the HQ-9B reportedly "
        "boasts a range of up to 300 kilometers."
    ),
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.18]\n"
        "YJ-12 ASCMs are supersonic, sea-skimming cruise missiles that may be "
        "launched from ships, aircraft, or truck-based TELs. The YJ-12E, also "
        "known by the export designator CM-302, has an advertised maximum range "
        "of 290 kilometers."
    ),
]

DEMO_AIRCRAFT_SNIPPETS: List[str] = [
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.12]\n"
        "The J-11 is a Chinese fourth-generation multirole fighter derived from "
        "the Russian Su-27. It has an estimated combat radius of approximately "
        "1,500 kilometers."
    ),
]

DEMO_RADAR_SNIPPETS: List[str] = [
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.21]\n"
        "The Type 305A is a Chinese air-surveillance radar with a reported "
        "maximum detection range of about 400 kilometers."
    ),
]

DEMO_OUTPOST_SNIPPETS: List[str] = [
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.9]\n"
        "Fiery Cross Reef has a 3,000-meter runway. Twenty-four fighter-size "
        "hangars are at the airfield. HQ-9B SAMs and YJ-12 anti-ship cruise "
        "missiles were deployed to Fiery Cross Reef in 2018. J-11 fighters and a "
        "Type 305A radar have also been observed there."
    ),
    (
        "[SOURCE: Dahm 2021, Offensive and Defensive Strike (JHU/APL), p.9]\n"
        "Mischief Reef has a 2,700-meter runway and twenty-four fighter-size "
        "hangars. HQ-9B SAMs and YJ-12 ASCMs were reported deployed in 2018."
    ),
]
