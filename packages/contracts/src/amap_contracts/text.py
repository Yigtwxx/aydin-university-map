"""Turkish-aware text normalization shared by the pipeline, database and API.

Python's ``str.lower()`` is locale-agnostic: ``"I".lower()`` gives ``"i"`` (Turkish
expects ``"ı"``) and ``"İ".lower()`` gives ``"i̇"`` (``i`` + combining dot). Every
place that matches or searches Turkish labels must go through these helpers so
that "KÜTÜPHANE", "Kütüphane" and "kutuphane" resolve to the same key.
"""

import re
import unicodedata

_TR_UPPER_TO_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_TR_TO_ASCII = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def lower_tr(text: str) -> str:
    """Lowercase ``text`` with Turkish dotted/dotless i rules."""
    return unicodedata.normalize("NFC", text).translate(_TR_UPPER_TO_LOWER).lower()


def search_key(text: str) -> str:
    """Return an ASCII, space-separated key for fuzzy matching and search indexes.

    >>> search_key("İnşaat Mühendisliği Lab.")
    'insaat muhendisligi lab'
    """
    folded = lower_tr(text).translate(_TR_TO_ASCII)
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM.sub(" ", ascii_only).strip()


# A floor number written with a hyphen or minus sign before it ("-2.Kat",
# "M Blok-4.Kat", "-5 Koridor"), or plainly as a floor ("2.Kat", "1. K").
_MINUS_NUMBER = re.compile("[-\\u2212]" + r"(\d+)(?!\d)")
_PLAIN_FLOOR = re.compile(r"(?:^|\s)(\d+)\s*\.\s*(?:Kat|K\b)", re.IGNORECASE)


def spells_other_floor(label: str, floor: int) -> bool:
    """The label writes this floor's number with the other sign.

    A tour label "T Blok -2.Kat" next to "2. kat" (or "T Blok 2.Kat" next to
    "-2. kat") would contradict itself on screen: callers then leave the
    floor out and let the label speak.
    """
    if floor > 0:
        return any(int(m) == floor for m in _MINUS_NUMBER.findall(label))
    if floor < 0:
        return any(int(m) == -floor for m in _PLAIN_FLOOR.findall(label))
    return False
