# app/interpretation/awb_vision_extractor.py
"""
AWB extractor backed by Claude Vision.
Accepts either raw PDF bytes + page range OR a plain OCR text string (fallback).
Returns the same dict schema used by AwbHybridExtractor so it is a drop-in
alternative in the UI.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .awb_llm_parser import parse_llm_json


def _normalize_hawb_key(hawb: Dict[str, Any]) -> str:
    raw = str(
        hawb.get("hawb_number")
        or hawb.get("hawbNumber")
        or hawb.get("hawb")
        or hawb.get("houseAirwaybillNumber")
        or ""
    )
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


def _dedupe_hawbs(hawbs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse duplicate HAWB entries Claude sometimes emits when the same
    house appears on more than one page (cover + manifest) — keeps the most
    complete record per unique hawb_number, preserving unresolved/empty keys.
    """
    best: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for hawb in hawbs:
        if not isinstance(hawb, dict):
            continue
        key = _normalize_hawb_key(hawb)
        if not key:
            order.append(f"__unkeyed_{len(order)}")
            best[order[-1]] = hawb
            continue
        if key not in best:
            order.append(key)
            best[key] = hawb
        else:
            score_new = sum(1 for v in hawb.values() if v not in (None, ""))
            score_old = sum(1 for v in best[key].values() if v not in (None, ""))
            if score_new > score_old:
                best[key] = hawb
    return [best[k] for k in order]


class AwbVisionExtractor:
    """Extract AWB fields using a configurable vision provider."""

    def __init__(
        self,
        provider_name: str = "claude",
        png_folder: Optional[str] = None,
        json_folder: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> None:
        self.provider_name = (provider_name or "claude").strip().lower()
        if self.provider_name == "msc_tech_ai" or self.provider_name == "msc-tech-ai" or self.provider_name == "msc-tech":
            from app.llm.msc_tech_ai_provider import MscTechAiProvider
            self._provider = MscTechAiProvider(
                png_folder=png_folder,
                json_folder=json_folder,
                group_label=group_label,
            )
        else:
            from app.llm.claude_vision_provider import ClaudeVisionProvider
            self._provider = ClaudeVisionProvider()

    # ------------------------------------------------------------------

    def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[Dict[int, int]] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send PDF page images to Claude Vision and return a structured dict.
        Returns the flat MAWB-only schema (legacy, single-AWB extraction).
        """
        raw_json = self._provider.extract_awb_json(
            pdf_bytes,
            start_page,
            end_page,
            page_rotations,
            awb_number=awb_number,
            group_label=group_label,
        )
        parsed = parse_llm_json(raw_json)
        return parsed.data

    def extract_mawb_with_hawbs(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[Dict[int, int]] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send all pages of a MAWB block (MAWB + HAWBs) to Claude Vision and
        return a structured dict:
          {
            "mawb":  { ...MAWB fields... },
            "hawbs": [ { ...HAWB fields... }, ... ]   # empty list if no HAWBs
          }

        Page orientation is corrected automatically using `page_rotations`
        (Tesseract OSD output from the presplit phase). Falls back to
        landscape heuristic if not provided.

        Falls back to flat MAWB-only extraction if Claude returns the old format.
        """
        raw_json = self._provider.extract_mawb_with_hawbs_json(
            pdf_bytes,
            start_page,
            end_page,
            page_rotations=page_rotations,
            awb_number=awb_number,
            group_label=group_label,
        )

        # Try to parse as the new nested format first.
        try:
            raw = raw_json.strip()
            # Strip possible code fences Claude might add despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
        except Exception:
            # json.loads failed — fall through to parse_llm_json
            parsed = parse_llm_json(raw_json)
            data = parsed.data

        # Normalise: if Claude returned a flat dict (no "mawb" key), wrap it.
        if "mawb" not in data:
            return {"mawb": data, "hawbs": []}

        # Some providers may return a null MAWB object. Treat that as an empty
        # dict so downstream UI code can safely attach the AWB number.
        if data.get("mawb") is None:
            data["mawb"] = {}

        # Accept the consolidated output shape used by ChatGPT/Claude prompts
        # while keeping the existing application's `hawbs` contract.
        if not isinstance(data.get("hawbs"), list) and isinstance(data.get("house_awbs"), list):
            data["hawbs"] = data["house_awbs"]

        # Ensure hawbs is always a list
        if not isinstance(data.get("hawbs"), list):
            data["hawbs"] = []

        data["hawbs"] = _dedupe_hawbs(data["hawbs"])

        return data

    def extract_from_text(self, ocr_text: str, awb_number: Optional[str] = None, group_label: Optional[str] = None) -> Dict[str, Any]:
        """
        Fallback: send raw OCR text to Claude (no image).
        Used when PDF bytes are unavailable (e.g. legacy text-only splits).
        """
        raw_json = self._provider.extract_from_text(
            ocr_text,
            awb_number=awb_number,
            group_label=group_label,
        )
        parsed = parse_llm_json(raw_json)
        return parsed.data
