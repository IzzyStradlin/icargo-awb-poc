# app/interpretation/awb_hybrid_extractor.py
"""
Hybrid AWB extraction: combines rule-based with LLM.
- Rule-based for structured fields (AWB, pieces, weight): reliable and fast
- LLM for text fields (shipper, consignee, goods_description): requires semantic intelligence
"""
from typing import Dict, Any, Optional
from .awb_field_detector import AwbFieldDetector
from ..llm.phi3_local_provider import Phi3LocalProvider


class AwbHybridExtractor:
    """Hybrid extractor that combines rule-based + LLM for better results."""

    def __init__(self, llm_provider=None):
        self.rule_based = AwbFieldDetector()
        # If no provider is passed, use Phi3LocalProvider as default
        if llm_provider is None:
            self.llm = Phi3LocalProvider()
        else:
            self.llm = llm_provider

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
            "goods_description": rule_result.data.goods_description,
            "shipper": rule_result.data.shipper,
            "consignee": rule_result.data.consignee,
            "flight_number": rule_result.data.flight_no,
            "flight_date": rule_result.data.flight_date,
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
        
        # Structured fields: ALWAYS rule-based (precise pattern matching)
        for field in ["awb_number", "pieces", "weight", "origin", "destination"]:
            result[field] = rule_data.get(field) or llm_data.get(field)
        
        # Shipper & Agent: ALWAYS rule-based (extracted reliably from sections, avoids boilerplate)
        result["shipper"] = rule_data.get("shipper") or llm_data.get("shipper")
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
        # goods_description: prefer rule-based patterns, then LLM
        result["goods_description"] = rule_data.get("goods_description") or llm_data.get("goods_description")
        
        # Flight info: prefer rule-based (pattern extraction is reliable), fallback to LLM
        result["flight_number"] = rule_data.get("flight_number") or llm_data.get("flight_number")
        result["flight_date"] = rule_data.get("flight_date") or llm_data.get("flight_date")
        
        return result
