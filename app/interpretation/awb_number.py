# app/interpretation/awb_number.py
from __future__ import annotations
import re
from typing import List, Optional

# Accepts: 001-33412551, 00133412551, 001 33412551, even with OCR adding spaces
AWB_RE = re.compile(r"\b([0-9OIl]{3})\s*[-]?\s*([0-9OIl]{8})\b")

def _fix_ocr_digits(s: str) -> str:
    # Minimal and safe OCR fix: O->0, I/l->1 (only where we expect digits)
    return (
        s.replace("O", "0").replace("o", "0")
         .replace("I", "1").replace("l", "1")
    )

def extract_awb_candidates(text: str) -> List[str]:
    cands = []
    for m in AWB_RE.finditer(text):
        p = _fix_ocr_digits(m.group(1))
        n = _fix_ocr_digits(m.group(2))
        if p.isdigit() and n.isdigit():
            cands.append(f"{p}-{n}")
    # Dedup preserving order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def best_awb(text: str) -> Optional[str]:
    cands = extract_awb_candidates(text)
    return cands[0] if cands else None