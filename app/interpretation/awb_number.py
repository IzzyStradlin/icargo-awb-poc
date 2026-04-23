# app/interpretation/awb_number.py
from __future__ import annotations
import re
from typing import List, Optional

# =========================================================
# Generic AWB regex (permissive - matches any 3-digit + 8-digit pattern)
# Accepts: 001-33412551, 00133412551, 001 33412551, 001/33412551, etc.
# Also handles spaces within the 8 digits: 001-1014 7701, 001-1022 1816, etc.
# Pattern: 3-digit prefix + optional separator + 1 digit + (optional space/dash + 1 digit){7}
# =========================================================
AWB_RE = re.compile(r"\b([0-9OIl]{3})\s*[-/]?\s*([0-9OIl](?:[\s-]*[0-9OIl]){7})\b")

# =========================================================
# MSC-specific AWB regexes for very noisy OCR.
# Goal: recognize MSC 233 MAWB numbers even when the prefix/serial is split by
# spaces, punctuation, airport codes, or OCR garbage.
MSC_PREFIX_RE = r"2[\s\-_/|\\.:]*3[\s\-_/|\\.:]*3"
MSC_SERIAL_RE = r"([1][0OIl4](?:[\s\-_/|\\.:]*[0-9OIl]){6})"

MSC_MAWB_PATTERNS = [
    re.compile(
        rf"\b{MSC_PREFIX_RE}\b\s*[^0-9]{{0,24}}?\s*{MSC_SERIAL_RE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{MSC_PREFIX_RE}\s*[^0-9]{{0,24}}?\b(MXP|HKG|MILAN|MALPENSA)?\b[^0-9]{{0,12}}?\s*{MSC_SERIAL_RE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{MSC_PREFIX_RE}\s*[-/|\\.: ]+\s*{MSC_SERIAL_RE}\b",
        re.IGNORECASE,
    ),
]

# Valid airline prefixes (IATA codes as 3-digit numbers)
# Restricted to only known carriers that appear in AWB documents
# 233 = MSC AIR (primary), add others as needed
VALID_AWB_PREFIXES = {"233"}  # Restricted to MSC AIR; extend as needed

# Legacy OCR corruption fallback: second digit read as arbitrary character
# (e.g. "140277562" -> "10277562", "170137859" from a VAT number must NOT match).
# Word boundaries prevent matching inside longer numbers.
_TERTIARY_RE = re.compile(r"\b([1])([^0OIl])([0OIl][0-9OIl]{6})\b", re.IGNORECASE)


def _fix_ocr_digits(s: str) -> str:
    # Minimal and safe OCR fix: O->0, I/l->1 (only where we expect digits)
    return (
        s.replace("O", "0").replace("o", "0")
         .replace("I", "1").replace("l", "1")
    )

def extract_awb_candidates(text: str, valid_prefixes: Optional[set] = None) -> List[str]:
    """
    Extract AWB candidates from text.
    
    Args:
        text: Text to search
        valid_prefixes: Set of valid AWB prefixes. If None, uses VALID_AWB_PREFIXES.
                       Set to None or empty set to accept all prefixes.
    
    Returns:
        List of normalized AWB candidates (format: XXX-XXXXXXXX)
    """
    if valid_prefixes is None:
        valid_prefixes = VALID_AWB_PREFIXES
    
    cands = []
    for m in AWB_RE.finditer(text):
        p = _fix_ocr_digits(m.group(1))
        n = _fix_ocr_digits(m.group(2)).replace(" ", "").replace("-", "")  # Remove spaces/dashes from 8 digits
        if p.isdigit() and n.isdigit():
            # If valid_prefixes is provided and non-empty, filter by prefix
            if valid_prefixes and p not in valid_prefixes:
                continue
            cands.append(f"{p}-{n}")
    # Dedup preserving order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def best_awb(text: str, valid_prefixes: Optional[set] = None) -> Optional[str]:
    """Get the first valid AWB candidate."""
    cands = extract_awb_candidates(text, valid_prefixes=valid_prefixes)
    return cands[0] if cands else None


def _normalize_msc_serial(serial_raw: str) -> Optional[str]:
    serial = _fix_ocr_digits(serial_raw).replace(" ", "").replace("-", "")
    serial = serial.replace("/", "").replace("|", "").replace(".", "").replace(":", "").replace("\\", "")
    if len(serial) != 8 or not serial.isdigit():
        return None
    if serial[1] == "4":
        serial = serial[0] + "0" + serial[2:]
    if not serial.startswith("10"):
        return None
    return serial


def _append_unique_awb(cands: List[str], serial: Optional[str]):
    if not serial:
        return
    awb = f"233-{serial}"
    if awb not in cands:
        cands.append(awb)


def extract_msc_awbs(text: str) -> List[str]:
    """
    Extract MSC MAWB numbers (233-10XXXXXX) using restrictive regex.
    More accurate for OCR text with garbage between prefix and serial.

    Tolerates OCR errors in second digit: "0" can be misread as "O", "4", etc.
    Pattern: 233 + [separator] + 1[0O4] + [6 digits] = standard 10XXXXXX format

    Returns:
        List of normalized MSC AWB candidates (format: 233-XXXXXXXX)
    """
    cands = []

    for pattern in MSC_MAWB_PATTERNS:
        for m in pattern.finditer(text):
            serial_raw = m.group(m.lastindex)
            _append_unique_awb(cands, _normalize_msc_serial(serial_raw))

    # Accept generic AWB candidates already normalized by the broader parser,
    # but keep only MSC numbers that resolve to the standard 10XXXXXX serial.
    for candidate in extract_awb_candidates(text, valid_prefixes={"233"}):
        _prefix, serial = candidate.split("-", 1)
        normalized = _normalize_msc_serial(serial)
        _append_unique_awb(cands, normalized)

    # Legacy OCR corruption fallback: 140277562 -> 10277562.
    # Word boundaries prevent false positives from VAT numbers (e.g. 1701378590119)
    # and ISO certificate numbers (e.g. 1400122015).
    for m in _TERTIARY_RE.finditer(text):
        first_digit = _fix_ocr_digits(m.group(1))
        remaining = _fix_ocr_digits(m.group(3))
        serial = first_digit + remaining.replace(" ", "").replace("-", "")
        _append_unique_awb(cands, _normalize_msc_serial(serial))
    
    # Dedup preserving order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out
