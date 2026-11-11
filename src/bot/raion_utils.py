"""Raion matching utilities for robust and canonical equality comparisons.

Prevents false-positive substring collisions between distinct raions
(e.g., 'Дністровський' vs 'Білгород-Дністровський',
       'Подільський' vs 'Кам'янець-Подільський' / 'Могилів-Подільський',
       'Луцький' vs 'Прилуцький',
       'Донецький' vs 'Сєвєродонецький')
while safely preserving de-communized aliases and apostrophe variations.
"""

from __future__ import annotations

import re
from typing import Set

APOSTROPHE_PATTERN = re.compile(r"[’ʼ`ʹ']")

# Canonical mappings for recent de-communized / renamed raions
RAION_ALIASES: dict[str, str] = {
    "червоноградський": "шептицький",
    "шептицький": "червоноградський",
    "новомосковський": "самарівський",
    "самарівський": "новомосковський",
    "красноградський": "берестинський",
    "берестинський": "красноградський",
    "новоград-волинський": "звягельський",
    "звягельський": "новоград-волинський",
    "володимир-волинський": "володимирський",
    "володимирський": "володимир-волинський",
}


def clean_apostrophe(text: str) -> str:
    """Normalizes all typographic apostrophe variants to standard ASCII apostrophe."""
    if not text:
        return ""
    return APOSTROPHE_PATTERN.sub("'", text)


def normalize_raion_name(name: str) -> str:
    """Strips 'район', normalizes case and apostrophes."""
    if not name:
        return ""
    cleaned = clean_apostrophe(name.lower()).replace(" район", "").strip()
    return cleaned


def get_raion_variants(name: str) -> Set[str]:
    """Generates a set of normalized equivalence variants for a raion name."""
    if not name:
        return set()
    cleaned = normalize_raion_name(name)
    if not cleaned:
        return set()

    base = re.sub(r"\(.*?\)", "", cleaned).strip()
    parens = [p.strip() for p in re.findall(r"\((.*?)\)", cleaned)]

    variants: Set[str] = {cleaned, base}
    for p in parens:
        if p:
            variants.add(p)

    for v in list(variants):
        if v in RAION_ALIASES:
            variants.add(RAION_ALIASES[v])

    return {v for v in variants if v}


def is_same_raion(name1: str, name2: str) -> bool:
    """Checks whether two raion name strings refer to the exact same territorial raion.

    Uses strict set-intersection of normalized canonical names and aliases.
    Strictly avoids substring 'in' collisions.
    """
    if not name1 or not name2:
        return False
    v1 = get_raion_variants(name1)
    v2 = get_raion_variants(name2)
    return bool(v1 & v2)
