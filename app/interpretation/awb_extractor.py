# app/interpretation/awb_extractor.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple


AWB_REGEX = re.compile(r"\b(\d{3})\s*[-]?\s*(\d{8})\b")  # 001-33412551 (anche con spazi)
IATA3_REGEX = re.compile(r"\b([A-Z]{3})\b")


@dataclass
class ExtractedField:
    name: str
    value: Optional[str]
    confidence: float = 0.0
    source: Optional[str] = None


@dataclass
class ExtractedAwb:
    # Key
    awb_number: Optional[str] = None          # "001-33412551"
    awb_prefix: Optional[str] = None          # "001"
    awb_serial: Optional[str] = None          # "33412551"
    awb_candidates: List[str] = field(default_factory=list)

    # Basic fields (PoC)
    origin: Optional[str] = None
    destination: Optional[str] = None
    pieces: Optional[str] = None
    weight: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None

    # Explainability
    fields: Dict[str, ExtractedField] = field(default_factory=dict)


class AwbExtractor:
    """
    PoC extractor: rule-based.
    Obiettivo: ricomporre campi leggibili e tirare fuori AWB number + candidati.
    """

    def extract(self, text: str) -> ExtractedAwb:
        out = ExtractedAwb()

        # --- AWB candidates ---
        candidates = self._extract_awb_candidates(text)
        out.awb_candidates = candidates

        # Pick first candidate as default (UI can allow user to choose)
        if candidates:
            out.awb_number = candidates[0]
            out.awb_prefix, out.awb_serial = candidates[0].split("-")
            out.fields["awb_number"] = ExtractedField(
                name="awb_number",
                value=out.awb_number,
                confidence=0.90,
                source="regex"
            )
        else:
            out.fields["awb_number"] = ExtractedField(
                name="awb_number",
                value=None,
                confidence=0.0,
                source=None
            )

        # --- Basic fields (light heuristics) ---
        origin, destination = self._extract_route(text)
        out.origin, out.destination = origin, destination
        out.fields["origin"] = ExtractedField("origin", origin, 0.60 if origin else 0.0, "heuristic")
        out.fields["destination"] = ExtractedField("destination", destination, 0.60 if destination else 0.0, "heuristic")

        pcs = self._extract_pieces(text)
        out.pieces = pcs
        out.fields["pieces"] = ExtractedField("pieces", pcs, 0.70 if pcs else 0.0, "regex/label")

        w = self._extract_weight(text)
        out.weight = w
        out.fields["weight"] = ExtractedField("weight", w, 0.70 if w else 0.0, "regex/label")

        shipper = self._extract_party(text, "SHIPPER")
        out.shipper = shipper
        out.fields["shipper"] = ExtractedField("shipper", shipper, 0.50 if shipper else 0.0, "label")

        consignee = self._extract_party(text, "CONSIGNEE")
        out.consignee = consignee
        out.fields["consignee"] = ExtractedField("consignee", consignee, 0.50 if consignee else 0.0, "label")

        return out

    def _extract_awb_candidates(self, text: str) -> List[str]:
        # Normalizza alcuni artefatti OCR comuni
        # (senza fare magie: solo rimuove spazi tra gruppi)
        cands = []
        for m in AWB_REGEX.finditer(text):
            prefix, serial = m.group(1), m.group(2)
            cands.append(f"{prefix}-{serial}")

        # Dedup preservando ordine
        seen = set()
        unique = []
        for c in cands:
            if c not in seen:
                unique.append(c)
                seen.add(c)

        return unique

    def _extract_route(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        # Cerca pattern tipo "FROM XXX TO YYY" / "ORIGIN XXX DEST YYY"
        m = re.search(r"\bFROM\s+([A-Z]{3})\b.*?\bTO\s+([A-Z]{3})\b", text, re.I | re.S)
        if m:
            return m.group(1).upper(), m.group(2).upper()

        m = re.search(r"\bORIGIN[:\s]+([A-Z]{3})\b.*?\bDEST(?:INATION)?[:\s]+([A-Z]{3})\b", text, re.I | re.S)
        if m:
            return m.group(1).upper(), m.group(2).upper()

        return None, None

    def _extract_pieces(self, text: str) -> Optional[str]:
        m = re.search(r"\bPCS[:\s]+(\d{1,6})\b", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"\bPIECES[:\s]+(\d{1,6})\b", text, re.I)
        if m:
            return m.group(1)
        return None

    def _extract_weight(self, text: str) -> Optional[str]:
        # KG / WT / WEIGHT
        m = re.search(r"\b(?:WT|WEIGHT)[:\s]+(\d+(?:\.\d+)?)\s*(KG|KGS)?\b", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(KG|KGS)\b", text, re.I)
        if m:
            return m.group(1)
        return None

    def _extract_party(self, text: str, label: str) -> Optional[str]:
        # prende la riga successiva a "SHIPPER:" / "CONSIGNEE:"
        # PoC: stop alla fine riga
        m = re.search(rf"\b{label}\b[:\s]+(.+)", text, re.I)
        if m:
            line = m.group(1).strip()
            # taglia se molto lunga
            return line[:200]
        return None