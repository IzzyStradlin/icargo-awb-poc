# app/interpretation/awb_llm_parser.py
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

JSON_BLOCK = re.compile(r"\{.*\}", re.S)

@dataclass
class AwbParsed:
    data: Dict[str, Any]
    awb_number: Optional[str]
    raw: str  # <-- aggiunto per debug

def parse_llm_json(raw: str) -> AwbParsed:
    s = (raw or "").strip()

    m = JSON_BLOCK.search(s)
    if m:
        s = m.group(0)

    try:
        obj = json.loads(s)
    except Exception as e:
        # rilancia mantenendo raw per debug UI
        raise ValueError(f"JSON parse error: {e}\nRAW:\n{s[:1500]}") from e

    awb = obj.get("awb_number")
    if awb and "-" not in awb and isinstance(awb, str) and awb.isdigit() and len(awb) == 11:
        awb = f"{awb[:3]}-{awb[3:]}"
        obj["awb_number"] = awb

    return AwbParsed(data=obj, awb_number=awb, raw=s)