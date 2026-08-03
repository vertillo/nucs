"""Artist-name helpers: normalization, featuring extraction, trivial filtering (spec 6.3/6.4)."""

from __future__ import annotations

import re
import unicodedata

_TRIVIAL_NAMES = frozenset(
    name.strip().lower() for name in ("various artists", "aa.vv.", "unknown artist", "unknown")
)

_GROUP_RE = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
_FEAT_KEYWORD_RE = re.compile(r"\b(?:feat\.|ft\.|featuring\b|con\b)", re.IGNORECASE)
# Comma splits even when attached ("A,B"); "&" and "e" only with surrounding
# whitespace so names like "R&B" or "R.E.M."-style attaches are never broken
# (spec 6.4.3: never split on an attached "&").
_NAME_SPLIT_RE = re.compile(r"\s*,\s*|\s+&\s+|\s+e\s+")


def normalize_name(s: str) -> str:
    """Normalize an artist name exactly as spec 6.3: NFKD, strip combining marks,
    lowercase, punctuation to spaces, underscore to space, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", s)
    no_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    lowered = no_marks.lower()
    no_punct = re.sub(r"[^\w\s]", " ", lowered).replace("_", " ")
    return re.sub(r"\s+", " ", no_punct).strip()


_TRIVIAL_NORMALIZED = frozenset(normalize_name(name) for name in _TRIVIAL_NAMES)


def extract_feat_from_title(title: str) -> list[str]:
    """Extract featured artist names from a title (spec 6.4.2).

    Only parenthesized/bracketed groups containing a ``feat.``/``ft.``/``featuring``/``con``
    keyword are considered; a bare suffix like ``" - feat. X"`` without parentheses is NOT
    handled in this phase (documented deviation; soft splits land in phase 04).
    Names inside the group are split on ``,``, ``&`` and `` e ``.
    """
    if not title:
        return []
    names: list[str] = []
    for group in _GROUP_RE.finditer(title):
        content = group.group(1) or group.group(2)
        match = _FEAT_KEYWORD_RE.search(content)
        if match is None:
            continue
        for part in _NAME_SPLIT_RE.split(content[match.end() :]):
            part = part.strip()
            if part:
                names.append(part)
    return names


def is_trivial_artist(name: str) -> bool:
    """True for hardcoded filler names or names shorter than 2 characters (spec 6.4.6)."""
    stripped = name.strip()
    if len(stripped) < 2:
        return True
    return stripped.lower() in _TRIVIAL_NAMES or normalize_name(stripped) in _TRIVIAL_NORMALIZED
