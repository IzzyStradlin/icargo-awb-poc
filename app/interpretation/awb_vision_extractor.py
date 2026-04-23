# app/interpretation/awb_vision_extractor.py
"""
AWB extractor backed by Claude Vision.
Accepts either raw PDF bytes + page range OR a plain OCR text string (fallback).
Returns the same dict schema used by AwbHybridExtractor so it is a drop-in
alternative in the UI.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .awb_llm_parser import parse_llm_json


class AwbVisionExtractor:
    """Extract AWB fields using Claude Vision."""

    def __init__(self) -> None:
        from app.llm.claude_vision_provider import ClaudeVisionProvider
        self._provider = ClaudeVisionProvider()

    # ------------------------------------------------------------------

    def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[Dict[int, int]] = None,
    ) -> Dict[str, Any]:
        """
        Send PDF page images to Claude Vision and return a structured dict.
        Returns the flat MAWB-only schema (legacy, single-AWB extraction).
        """
        raw_json = self._provider.extract_awb_json(pdf_bytes, start_page, end_page, page_rotations)
        parsed = parse_llm_json(raw_json)
        return parsed.data

    def extract_mawb_with_hawbs(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[Dict[int, int]] = None,
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
            pdf_bytes, start_page, end_page, page_rotations=page_rotations
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

        # Ensure hawbs is always a list
        if not isinstance(data.get("hawbs"), list):
            data["hawbs"] = []

        return data

    def extract_from_text(self, ocr_text: str) -> Dict[str, Any]:
        """
        Fallback: send raw OCR text to Claude (no image).
        Used when PDF bytes are unavailable (e.g. legacy text-only splits).
        """
        raw_json = self._provider.extract_from_text(ocr_text)
        parsed = parse_llm_json(raw_json)
        return parsed.data
