"""
LLM-based AWB Extractor
Uses LLM with structured prompts to extract AWB fields from OCR text
"""

import json
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class AwbLlmExtractor:
    """
    Extract AWB fields from OCR text using LLM.
    """
    
    def __init__(self, llm):
        """
        Args:
            llm: LLM provider with extract_awb_json() method
        """
        self.llm = llm
    
    def extract(self, text: str) -> Dict[str, Any]:
        """
        Extract AWB fields from OCR text using LLM with structured prompt.
        
        Args:
            text: OCR-extracted text from AWB document
        
        Returns:
            Dict with fields: awb_number, shipper, consignee, origin, destination,
                            pieces, weight, flight_number, flight_date, goods_description
        """
        from app.interpretation.awb_extraction_prompt import AWB_STRUCTURE_PROMPT_COMPACT
        
        # Prepare OCR text with compact structured guidance for the LLM
        # Use compact version to stay within token limits of quantized models
        enhanced_ocr_text = f"""{AWB_STRUCTURE_PROMPT_COMPACT}

OCR TEXT TO EXTRACT:
{text}

Return JSON:
"""
        
        # Call LLM with enhanced OCR text
        try:
            llm_response = self.llm.extract_awb_json(enhanced_ocr_text)
            
            # Parse JSON response
            result = json.loads(llm_response)
            
            # Clean up the result
            return self._clean_extraction(result)
        except Exception as e:
            print(f"LLM extraction error: {e}")
            return self._empty_result()
    
    def _clean_extraction(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean up extracted fields
        
        Args:
            result: Raw extraction result from LLM
        
        Returns:
            Cleaned extraction result
        """
        cleaned = {}

        # Standard string fields
        str_fields = [
            'awb_number', 'shipper', 'shipper_address', 'shipper_street', 'shipper_city',
            'shipper_province', 'shipper_zip', 'shipper_country',
            'consignee', 'consignee_address', 'consignee_street', 'consignee_city',
            'consignee_province', 'consignee_zip', 'consignee_country',
            'agent', 'agent_address', 'agent_street', 'agent_city',
            'agent_province', 'agent_zip', 'agent_country',
            'origin', 'destination', 'flight_number', 'flight_date', 'goods_description',
        ]
        for key in str_fields:
            value = result.get(key)
            if value and isinstance(value, str):
                value = value.strip()
                if not value or value.lower() == 'null':
                    value = None
            elif not isinstance(value, str):
                value = None
            cleaned[key] = value

        # Numeric fields
        for key in ['pieces', 'weight', 'chargeable_weight', 'rate', 'total_charge']:
            value = result.get(key)
            if value is not None:
                try:
                    cleaned[key] = int(value) if key == 'pieces' else float(value)
                except (TypeError, ValueError):
                    cleaned[key] = None
            else:
                cleaned[key] = None

        return cleaned
    
    def _empty_result(self) -> Dict[str, Any]:
        """
        Return empty extraction result
        
        Returns:
            Dict with all fields set to None
        """
        return {
            'awb_number': None,
            'shipper': None,
            'shipper_address': None, 'shipper_street': None, 'shipper_city': None,
            'shipper_province': None, 'shipper_zip': None, 'shipper_country': None,
            'consignee': None,
            'consignee_address': None, 'consignee_street': None, 'consignee_city': None,
            'consignee_province': None, 'consignee_zip': None, 'consignee_country': None,
            'agent': None,
            'agent_address': None, 'agent_street': None, 'agent_city': None,
            'agent_province': None, 'agent_zip': None, 'agent_country': None,
            'origin': None,
            'destination': None,
            'pieces': None,
            'weight': None,
            'chargeable_weight': None,
            'rate': None,
            'total_charge': None,
            'flight_number': None,
            'flight_date': None,
            'goods_description': None,
        }
