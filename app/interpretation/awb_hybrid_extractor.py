# app/interpretation/awb_hybrid_extractor.py
"""
Hybrid AWB extraction: combines rule-based with LLM.
- Rule-based for structured fields (AWB, pieces, weight): reliable and fast
- LLM for text fields (shipper, consignee, goods_description): requires semantic intelligence
"""
import re
from typing import Dict, Any, Optional, List
from .awb_field_detector import AwbFieldDetector

# IATA flight number: 2 uppercase letters + 2-5 digits, optionally followed by 1 letter suffix
# Examples: CP0137, LH2054, AZ0203, BA456
_FLIGHT_RE = re.compile(r'^[A-Z]{2}\d{2,5}[A-Z]?$')
# Known AWB prefixes that should NEVER appear in a flight number
_AWB_PREFIXES = {'233', '020', '057', '074', '098', '127', '160', '176', '180', '217', '618'}

# Carrier/airline keywords that should NEVER be used as shipper or consignee
_CARRIER_KEYWORDS = {
    'MSC AIR', 'ALISCARGO', 'LUFTHANSA', 'AIR FRANCE', 'KLM', 'BRITISH AIRWAYS',
    'UNITED AIRLINES', 'DELTA AIR', 'CATHAY PACIFIC', 'EMIRATES', 'CARGOLUX',
    'KOREAN AIR', 'SINGAPORE AIRLINES', 'JAPAN AIRLINES', 'QANTAS',
    'IBERIA', 'SWISS AIR', 'TURKISH AIRLINES', 'ETIHAD',
}


def _is_carrier(name: Optional[str]) -> bool:
    """Return True if the name looks like an airline/carrier rather than a shipper."""
    if not name:
        return False
    upper = name.upper()
    return any(kw in upper for kw in _CARRIER_KEYWORDS)


def _validate_flight_number(flight: Optional[str]) -> Optional[str]:
    """
    Returns the flight number if it looks like a valid IATA code, else None.
    Rejects values whose numeric suffix EXACTLY matches a known AWB prefix (e.g. 'IN233' where digits='233').
    """
    if not flight:
        return None
    f = flight.strip().upper().replace(' ', '').replace('-', '').replace('/', '')
    # Must match IATA pattern: 2 letters + 2-5 digits + optional letter suffix
    m = re.match(r'^([A-Z]{2})(\d{2,5})([A-Z]?)$', f)
    if not m:
        return None
    digits = m.group(2)
    # Reject if the numeric part EXACTLY matches a known AWB prefix (e.g. digits='233')
    if digits in _AWB_PREFIXES:
        return None
    return f"{m.group(1)}{m.group(2)}{m.group(3)}"


class AwbHybridExtractor:
    """Hybrid extractor that combines rule-based + LLM for better results."""

    def __init__(self, llm_provider=None):
        self.rule_based = AwbFieldDetector()
        self.llm = llm_provider  # None = rule-based only fallback

    def extract(self, text: str, sections=None) -> Dict[str, Any]:
        """
        Extracts AWB fields using hybrid approach:
        1. Rule-based for structured fields (using sections if available)
        2. LLM for text fields (semantics)
        
        Args:
            text: OCR extracted text
            sections: Optional dict with section data (shipper, consignee, cargo, etc.)
        
        Returns: dict with all fields (which can be None)
        """
        
        # 1) Rule-based extraction (fast, reliable for fixed formats)
        # Pass sections to field detector for section-aware extraction
        rule_result = self.rule_based.extract(text, sections=sections)
        # Convert AwbData to dict (note: AwbData uses flight_no, not flight_number)
        rule_data = {
            "awb_number": rule_result.data.awb_number,
            "origin": rule_result.data.origin,
            "destination": rule_result.data.destination,
            "agent": rule_result.data.agent,
            "pieces": rule_result.data.pieces,
            "weight": rule_result.data.weight,
            "chargeable_weight": rule_result.data.chargeable_weight,
            "rate": rule_result.data.rate,
            "total_charge": rule_result.data.total_charge,
            "goods_description": rule_result.data.goods_description,
            "shipper": rule_result.data.shipper,
            "consignee": rule_result.data.consignee,
            "flight_number": rule_result.data.flight_no,
            "flight_date": rule_result.data.flight_date,
            # Address fields - rule-based doesn't extract structured addresses
            "shipper_address": rule_result.data.shipper_address,
            "consignee_address": rule_result.data.consignee_address,
            "agent_address": rule_result.data.agent_address,
        }
        
        # 2) LLM extraction (for text fields)
        llm_json_str = self.llm.extract_awb_json(text)
        try:
            import json
            llm_data = json.loads(llm_json_str)
        except Exception:
            llm_data = {}
        
        # 3) Intelligent merge: rule-based for structured, LLM for text
        merged = self._merge_results(rule_data, llm_data)
        
        return merged


    def extract_all(
        self, 
        texts: List[str], 
        sections_list: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract AWB fields from multiple text blocks using hybrid approach.
        
        Args:
            texts: List of text strings (one per AWB document)
            sections_list: Optional list of section dicts (parallel to texts)
        
        Returns:
            List of dicts, one per input text
        """
        results = []
        sections_list = sections_list or [None] * len(texts)
        
        for text, sections in zip(texts, sections_list):
            result = self.extract(text, sections)
            results.append(result)
        
        return results

    def _merge_results(self, rule_data: Dict[str, Any], llm_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Intelligent merge strategy:
        - Structured fields (awb, pieces, weight, origin, dest, agent): ALWAYS rule-based (precise formats)
        - shipper, agent: ALWAYS rule-based (more reliable, avoids boilerplate)
        - consignee: prefer LLM for semantic accuracy, fallback to rule-based only if LLM is None
          BUT: reject rule-based if it equals shipper (likely extraction error)
        - goods_description: prefer LLM for semantic accuracy, fallback to rule-based
        - flight_number, flight_date: prefer rule-based for precision, fallback to LLM
        """
        
        result = {}
        
        # AWB number: rule-based is more reliable (regex on fixed format)
        result["awb_number"] = rule_data.get("awb_number") or llm_data.get("awb_number")

        # Weight: rule-based wins (numeric pattern matching is precise)
        result["weight"] = rule_data.get("weight") or llm_data.get("weight")

        # Origin/Destination: LLM wins — it understands context (shipper city→origin airport,
        # consignee city→destination airport). Rule-based fallback is too error-prone:
        # the IATA fallback regex can match common words (e.g. "HKG" appearing in consignee
        # address section before the routing section, giving wrong origin/destination order).
        result["origin"] = llm_data.get("origin") or rule_data.get("origin")
        result["destination"] = llm_data.get("destination") or rule_data.get("destination")

        # Pieces: LLM wins — the LLM is explicitly instructed to use "No. Of Pieces RCP" column only,
        # NOT counts found in goods description text (e.g. "239 PCS ON PMC...").
        # SANITY CAP: reject LLM value if > 9999 (likely confusion with total_charge or other large number).
        llm_pieces = llm_data.get("pieces")
        if isinstance(llm_pieces, (int, float)) and llm_pieces > 9999:
            llm_pieces = None  # e.g. 12375 is total_charge, not pieces
        result["pieces"] = llm_pieces or rule_data.get("pieces")
        
        # Shipper: LLM primary — because OCR merges left+right columns, rule-based will pick up
        # both shipper and consignee text on the same line; LLM understands 2-column semantics.
        # Rule-based is fallback only. Filter carrier names from both sources.
        rule_shipper = rule_data.get("shipper")
        llm_shipper = llm_data.get("shipper")
        if _is_carrier(rule_shipper):
            rule_shipper = None
        if _is_carrier(llm_shipper):
            llm_shipper = None
        result["shipper"] = llm_shipper or rule_shipper

        result["agent"] = rule_data.get("agent") or llm_data.get("agent")
        
        # Consignee: complex logic - reject rule-based if it matches shipper
        # If LLM returns something different, use it. Otherwise fallback to rule-based if valid.
        rule_consignee = rule_data.get("consignee")
        llm_consignee = llm_data.get("consignee")
        shipper = rule_data.get("shipper")
        
        # If rule-based consignee equals shipper, don't use rule-based (extraction error)
        if rule_consignee and shipper and rule_consignee.upper() == shipper.upper():
            # Rule-based matched shipper (bad), prefer LLM
            result["consignee"] = llm_consignee
        else:
            # Rule-based is different from shipper (good) OR shipper is None
            # Use LLM if available, fallback to rule-based if LLM is NULL
            result["consignee"] = llm_consignee or rule_consignee
        
        # Text fields: prefer rule-based first (it's more reliable), fallback to LLM
        # goods_description: LLM preferred (full verbatim), fallback to rule-based
        result["goods_description"] = llm_data.get("goods_description") or rule_data.get("goods_description")
        
        # Flight info: prefer LLM for flight_number (LLM constrained to Flight/Date field), fallback to rule-based
        # Validate both candidates — reject anything that looks like an AWB prefix or non-IATA code
        llm_flight = _validate_flight_number(llm_data.get("flight_number"))
        rule_flight = _validate_flight_number(rule_data.get("flight_number"))
        result["flight_number"] = llm_flight or rule_flight
        result["flight_date"] = rule_data.get("flight_date") or llm_data.get("flight_date")

        # Chargeable weight: rule-based wins when it found a LABELED value (reliable).
        # SANITY CHECK: if rule-based value equals total_charge (likely wrong extraction from
        # table totals row), reject it and fall back to LLM.
        rule_cw = rule_data.get("chargeable_weight")
        llm_cw = llm_data.get("chargeable_weight")
        rule_tc = rule_data.get("total_charge")
        llm_tc = llm_data.get("total_charge")
        tc_val = rule_tc or llm_tc
        # Reject rule_cw if it matches total_charge (confusion: 12375 = total, not chargeable weight)
        if rule_cw is not None and tc_val is not None and abs(rule_cw - tc_val) < 1:
            rule_cw = None
        # Reject llm_cw if it matches total_charge (LLM column-order confusion)
        if llm_cw is not None and tc_val is not None and abs(llm_cw - tc_val) < 1:
            llm_cw = None
        result["chargeable_weight"] = rule_cw or llm_cw

        # Rate: rule-based wins when labeled (e.g. "Rate/Charge 4.5"); LLM fallback
        result["rate"] = rule_data.get("rate") or llm_data.get("rate")

        # Total charge: rule-based wins (parsed directly from the RCP data row); LLM fallback.
        # Computed fallback = chargeable_weight × rate if both are available.
        total = rule_tc or llm_data.get("total_charge")
        if total is None:
            cw = result.get("chargeable_weight")
            r = result.get("rate")
            if cw is not None and r is not None:
                total = round(cw * r, 2)
        result["total_charge"] = total

        # Computed chargeable_weight fallback: if still None, derive from total_charge / rate.
        # Also catches the case where rule_cw was wrong (e.g. = total_charge) and LLM also failed.
        if result.get("chargeable_weight") is None:
            tc = result.get("total_charge")
            r2 = result.get("rate")
            if tc and r2 and r2 > 0:
                result["chargeable_weight"] = round(tc / r2, 2)

        # Address fields: LLM wins (semantic extraction), fallback to rule-based flat strings
        for field in [
            "shipper_address", "shipper_street", "shipper_city", "shipper_province", "shipper_zip", "shipper_country",
            "consignee_address", "consignee_street", "consignee_city", "consignee_province", "consignee_zip", "consignee_country",
            "agent_address", "agent_street", "agent_city", "agent_province", "agent_zip", "agent_country",
        ]:
            result[field] = llm_data.get(field) or rule_data.get(field)

        return result
