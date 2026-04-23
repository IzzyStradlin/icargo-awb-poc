# app/llm/claude_vision_provider.py
"""
Claude 3.5 Sonnet Vision provider for AWB extraction.
Renders PDF pages to images and sends them directly to Claude Vision —
no regex, no rule-based parsing: the model reads the layout visually.
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Optional

import httpx


_EXTRACTION_PROMPT = """\
You are an expert in IATA Air Waybill (AWB) document parsing.
I am showing you one or more images of an Air Waybill form.
Extract ALL of the following fields and return ONLY a valid JSON object — no markdown, no code fences, no explanation.

== FORM LAYOUT ==
The AWB has a 2-column layout:
  - LEFT column  → Shipper information
  - RIGHT column → Consignee information
The routing / To-By table row format is: DESTINATION (3 letters) | CARRIER (2 letters) | FLIGHT/DATE
Example: "HKG | CP | 113/19"  →  flight_number = "CP113", destination = "HKG"

== FIELDS (use exactly these JSON keys, set null if not found) ==
awb_number        — format NNN-NNNNNNNN (e.g. 233-10166763)
origin            — IATA 3-letter departure airport code
destination       — IATA 3-letter destination airport code
shipper           — full company name from "Shipper's Name and Address" box (top-left)
shipper_street    — street address of shipper
shipper_city      — city of shipper
shipper_province  — province/state of shipper
shipper_zip       — postal code of shipper
shipper_country   — 2-letter ISO country code of shipper
consignee         — full company name from "Consignee's Name and Address" box (top-right)
consignee_street  — street address of consignee
consignee_city    — city of consignee
consignee_province— province/state of consignee
consignee_zip     — postal code of consignee
consignee_country — 2-letter ISO country code of consignee
agent             — company name from "Issuing Carrier's Agent Name and City" box
agent_street      — street address of agent
agent_city        — city of agent
agent_province    — province/state of agent
agent_zip         — postal code of agent
agent_country     — 2-letter ISO country code of agent
pieces            — integer from "No. Of Pieces RCP" column (small number 1-999, NOT the charge total)
weight            — gross weight in kg (numeric, no units)
chargeable_weight — chargeable weight in kg from the "Chargeable Weight" column (may differ from gross weight)
rate              — rate per kg from "Rate/Charge" column (numeric)
total_charge      — total charge from "Total" column (numeric)
flight_number     — 2-letter airline code + numeric flight (e.g. CP113, LH2054) from the To/By routing row
flight_date       — date from flight/date field in YYYY-MM-DD format
goods_description — full verbatim text from "Nature and Quantity of Goods" column

Return ONLY the JSON object.\
"""

_MAWB_HAWB_PROMPT = """\
You are an expert in IATA Air Waybill (AWB) document parsing.
I am showing you images of one shipment package that contains:
  1. ONE Master Air Waybill (MAWB) — usually PORTRAIT orientation, first image(s)
  2. ZERO OR MORE House Air Waybills (HAWB) — usually LANDSCAPE orientation, subsequent images

Some images may be rotated 90°. Read them accordingly — do not skip rotated pages.

Extract ALL fields and return ONLY a valid JSON object with this exact structure (no markdown, no code fences):
{
  "mawb": { ...MAWB fields... },
  "hawbs": [ { ...HAWB fields... }, ... ]
}

hawbs must be an array (empty [] if no HAWBs found).

== MAWB FIELDS (under "mawb" key) ==
awb_number        — MAWB number, format NNN-NNNNNNNN (e.g. 233-10166763)
origin            — IATA 3-letter departure airport
destination       — IATA 3-letter destination airport
shipper           — shipper company name
shipper_street / shipper_city / shipper_province / shipper_zip / shipper_country
consignee         — consignee company name
consignee_street / consignee_city / consignee_province / consignee_zip / consignee_country
agent             — issuing carrier's agent name
agent_street / agent_city / agent_province / agent_zip / agent_country
pieces            — total number of pieces (integer)
weight            — total gross weight in kg (numeric)
chargeable_weight — total chargeable weight in kg (numeric)
rate              — rate per kg (numeric)
total_charge      — total charge (numeric)
flight_number     — 2-letter airline code + flight number (e.g. CP113)
flight_date       — flight date in YYYY-MM-DD
goods_description — full description of goods

== HAWB FIELDS (each element in "hawbs" array) ==
hawb_number          — House AWB number (any format, e.g. HAWB-12345 or 123-45678901)
origin               — IATA 3-letter departure airport
destination          — IATA 3-letter destination airport
shipper              — shipper company name
shipper_street / shipper_city / shipper_province / shipper_zip / shipper_country
consignee            — consignee company name
consignee_street / consignee_city / consignee_province / consignee_zip / consignee_country
notify_party         — notify party full name and address (free text, null if absent)
pieces               — number of pieces (integer)
weight               — gross weight in kg (numeric)
chargeable_weight    — chargeable weight in kg (numeric)
volume               — volume in CBM / m³ (numeric, null if not stated)
dimensions           — package dimensions as free text (e.g. "60x40x30 cm"), null if not stated
hs_code              — HS / Harmonized System commodity code (e.g. "8471.30"), null if not stated
goods_description    — full verbatim description of goods / nature of goods
special_handling     — special handling codes (e.g. "PER", "AVI", "HUM", "DGR"), null if absent
declared_value_carriage  — declared value for carriage (numeric or string, null if not stated)
declared_value_customs   — declared value for customs (numeric or string, null if not stated)
rate                 — rate per kg (numeric, null if not stated)
total_charge         — total charge (numeric, null if not stated)
flight_number        — flight number (e.g. CP113), null if not stated
flight_date          — flight date in YYYY-MM-DD, null if not stated

Return ONLY the JSON object.\
"""


class ClaudeVisionProvider:
    """Sends PDF page images to Claude Vision for AWB extraction."""

    # Override via CLAUDE_MODEL env var.
    # Available on this account (Claude 4 generation):
    #   claude-haiku-4-5-20251001   ← fast & cheap, good for structured extraction
    #   claude-sonnet-4-5-20250929  ← better quality
    #   claude-sonnet-4-6           ← latest sonnet
    MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY non trovata nell'ambiente. "
                "Aggiungi ANTHROPIC_API_KEY=sk-ant-... al file .env"
            )
        timeout = float(os.getenv("CLAUDE_TIMEOUT", "120"))
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=30.0),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_pages(self, pdf_bytes: bytes, start_page: int, end_page: int) -> list[str]:
        """Render PDF pages [start_page, end_page] to base64 PNG strings (2× DPI).

        start_page / end_page are 1-based (as stored by AwbDocumentPreSplitter).
        PyMuPDF uses 0-based indices, so we convert here.
        If both are 0 (legacy / unknown), we fall back to page 0 only.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise RuntimeError(
                "PyMuPDF non installato. Esegui: pip install pymupdf"
            )

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total = len(doc)

        # Convert 1-based presplitter indices to 0-based fitz indices.
        # Guard: if start_page==0 (not set), default to first page.
        fitz_start = max(0, start_page - 1) if start_page > 0 else 0
        fitz_end = max(0, end_page - 1) if end_page > 0 else fitz_start

        b64_pages: list[str] = []
        for p in range(fitz_start, min(fitz_end + 1, total)):
            mat = fitz.Matrix(1.5, 1.5)  # ~108 DPI — good quality, stays under 5 MB limit
            pix = doc[p].get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            png_bytes = pix.tobytes("png")
            # If still over 4 MB, downsample further to avoid Anthropic 400
            if len(png_bytes) > 4 * 1024 * 1024:
                mat2 = fitz.Matrix(1.0, 1.0)
                pix = doc[p].get_pixmap(matrix=mat2, colorspace=fitz.csRGB)
                png_bytes = pix.tobytes("png")
            b64_pages.append(base64.standard_b64encode(png_bytes).decode())
        doc.close()
        return b64_pages

    def _call_api(self, content: list, max_tokens: int = 2048) -> str:
        payload = {
            "model": self.MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._http.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
            except httpx.HTTPStatusError as e:
                last_err = e
                try:
                    detail = e.response.json()
                except Exception:
                    detail = e.response.text
                if e.response.status_code in (429, 529):
                    time.sleep(2.0 * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"Anthropic API {e.response.status_code}: {detail}"
                    ) from e
            except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Claude Vision call failed after retries: {last_err}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_awb_json(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
    ) -> str:
        """
        Send PDF page images to Claude Vision and return a raw JSON string
        containing extracted AWB fields.

        Parameters
        ----------
        pdf_bytes  : raw bytes of the full PDF
        start_page : 0-based first page of this AWB (inclusive)
        end_page   : 0-based last  page of this AWB (inclusive)
        """
        b64_images = self._render_pages(pdf_bytes, start_page, end_page)
        if not b64_images:
            raise ValueError(
                f"No pages found in range {start_page}-{end_page}"
            )

        # Build multi-modal content: image(s) + prompt text.
        # Limit to first 2 pages to stay well within token budget.
        content: list = []
        for b64 in b64_images[:2]:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        content.append({"type": "text", "text": _EXTRACTION_PROMPT})

        return self._call_api(content)

    def extract_mawb_with_hawbs_json(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        max_images: int = 10,
    ) -> str:
        """
        Send all pages of a MAWB block (including any HAWB pages that follow)
        to Claude Vision and return a JSON string with structure:
          { "mawb": {...}, "hawbs": [{...}, ...] }

        The first page(s) are the MAWB (typically portrait).
        Subsequent pages are HAWBs (typically landscape — Claude reads them natively).

        Parameters
        ----------
        pdf_bytes  : raw bytes of the full PDF
        start_page : 1-based first page (presplitter convention)
        end_page   : 1-based last page  (presplitter convention)
        max_images : safety cap — never send more than this many images per call
        """
        b64_images = self._render_pages(pdf_bytes, start_page, end_page)
        if not b64_images:
            raise ValueError(
                f"No pages found in range {start_page}-{end_page}"
            )

        content: list = []
        for b64 in b64_images[:max_images]:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        content.append({"type": "text", "text": _MAWB_HAWB_PROMPT})

        return self._call_api(content, max_tokens=8192)

    def extract_from_text(self, ocr_text: str) -> str:
        """
        Fallback: send raw OCR text (no image) to Claude for extraction.
        Useful when a PDF page image is unavailable (e.g. text-only splits).
        """
        user_msg = (
            _EXTRACTION_PROMPT
            + "\n\n== OCR TEXT (may have garbling) ==\n"
            + ocr_text[:15000]
        )
        content = [{"type": "text", "text": user_msg}]
        return self._call_api(content)
