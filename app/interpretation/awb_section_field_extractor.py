"""
AWB Section-Based Field Extractor

Improved LLM-based extraction that leverages document sections.
Instead of asking the LLM to extract from raw text, we ask specific questions
about specific sections, dramatically reducing ambiguity and errors.

Strategy:
- For each field, use only the relevant section(s)
- Ask specific, constrained questions instead of generic ones
- Provide few-shot examples for better performance
- Force structured JSON output with schema validation
"""

import json
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class ExtractedField:
    """Represents an extracted field with value and confidence."""
    value: Optional[str]
    confidence: float = 0.0
    source_section: str = ""
    reasoning: str = ""


class AwbSectionBasedFieldExtractor:
    """
    Extract AWB fields using section-aware LLM prompts.
    Each field is extracted with context-specific questions.
    """

    def __init__(self, llm_provider):
        """
        Args:
            llm_provider: LLM provider with extract_awb_json() method
        """
        self.llm = llm_provider

    def extract_from_sections(
        self, 
        sections: Dict[str, str],
        full_text: str
    ) -> Dict[str, Any]:
        """
        Extract all AWB fields using section-aware approach.
        
        Args:
            sections: Dictionary with section texts (from AwbSectionAnalyzer)
            full_text: Full OCR text (fallback)
            
        Returns:
            Dictionary with all extracted fields
        """
        results = {
            'awb_number': self._extract_awb_number(full_text),
            'shipper': self._extract_shipper(sections.get('shipper', '')),
            'consignee': self._extract_consignee(sections.get('consignee', '')),
            'agent': self._extract_agent(sections.get('agent', sections.get('shipper', ''))),
            'origin': self._extract_origin(sections.get('handling', '') or full_text),
            'destination': self._extract_destination(sections.get('handling', '') or full_text),
            'pieces': self._extract_pieces(sections.get('cargo', '') or full_text),
            'weight': self._extract_weight(sections.get('cargo', '') or full_text),
            'goods_description': self._extract_goods_description(sections.get('cargo', '')),
            'flight_number': self._extract_flight_number(sections.get('handling', '')),
            'flight_date': self._extract_flight_date(sections.get('handling', '')),
        }
        
        return results

    def _extract_awb_number(self, text: str) -> ExtractedField:
        """
        Extract AWB number using rule-based approach (most reliable).
        Format: XXX-YYYYYYYY (3 digits - 8 digits)
        """
        pattern = r'\b(\d{3})[-\s]?(\d{8})\b'
        match = re.search(pattern, text)
        
        if match:
            prefix, serial = match.group(1), match.group(2)
            value = f"{prefix}-{serial}"
            return ExtractedField(
                value=value,
                confidence=0.98,
                source_section="full_text",
                reasoning="Matched standard AWB pattern"
            )
        
        return ExtractedField(value=None, confidence=0.0)

    def _extract_shipper(self, shipper_section: str) -> ExtractedField:
        """
        Extract shipper company name from shipper section.
        
        Uses LLM with specific guidance:
        - Extract ONLY company name (not address or legal text)
        - First line is usually the company name
        """
        if not shipper_section or len(shipper_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=shipper_section,
            field_name="SHIPPER",
            instructions=[
                "Extract ONLY the company name from the shipper section",
                "Do NOT include address, city, or postal code",
                "Extract from the first line(s) of the section",
                "If multiple lines exist before the address, join them as one company name",
                "Return null if unclear"
            ],
            examples={
                "DHL Supply Chain Italy\\nVia Roma 123\\n20100 Milano": "DHL Supply Chain Italy",
                "Ferrari S.p.A.\\nMaranello (MO)": "Ferrari S.p.A.",
                "Pirelli Group\\nViale Piero e Alberto Pirelli 25\\nMilano": "Pirelli Group"
            }
        )
        
        return self._call_llm_field_extraction(prompt, "shipper")

    def _extract_consignee(self, consignee_section: str) -> ExtractedField:
        """
        Extract consignee company name from consignee section.
        
        Similar to shipper extraction but for receiving party.
        """
        if not consignee_section or len(consignee_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=consignee_section,
            field_name="CONSIGNEE",
            instructions=[
                "Extract ONLY the company name from the consignee section",
                "Do NOT include address, city, or postal code",
                "Extract from the first line(s) of the section",
                "If multiple lines exist before the address, join them as one company name",
                "Return null if unclear"
            ],
            examples={
                "BMW Munich Distribution\\nAmalienburgstrasse 1\\n80135 München": "BMW Munich Distribution",
                "Porsche Logistics GmbH\\nWeissach": "Porsche Logistics GmbH"
            }
        )
        
        return self._call_llm_field_extraction(prompt, "consignee")

    def _extract_agent(self, agent_section: str) -> ExtractedField:
        """Extract freight forwarder or customs broker (agent)."""
        if not agent_section or len(agent_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=agent_section,
            field_name="AGENT",
            instructions=[
                "Extract the freight forwarder or customs broker name",
                "Usually a logistics company like DHL, FedEx, UPS, etc.",
                "Extract only the company name",
                "Return null if this section doesn't contain agent information"
            ]
        )
        
        return self._call_llm_field_extraction(prompt, "agent")

    def _extract_origin(self, handling_section: str) -> ExtractedField:
        """
        Extract origin airport code (departure point).
        Must be exactly 3 uppercase letters (IATA code).
        """
        if not handling_section or len(handling_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=handling_section,
            field_name="ORIGIN AIRPORT",
            instructions=[
                "Find the 3-letter IATA airport code for DEPARTURE point",
                "MUST be exactly 3 uppercase letters",
                "Common codes: MXP (Milan), FCO (Rome), VCE (Venice), CDG (Paris), AMS (Amsterdam)",
                "Return ONLY the 3-letter code, nothing else",
                "Return null if no valid 3-letter code found"
            ],
            examples={
                "Origin: Milano (MXP)\\nDestination: London": "MXP",
                "FROM: FCO TO: JFK": "FCO",
                "Departure airport: MXPB": None  # Invalid - too long
            }
        )
        
        field = self._call_llm_field_extraction(prompt, "origin")
        
        # Validate it's exactly 3 letters
        if field.value and len(field.value) == 3 and field.value.isupper():
            return field
        
        return ExtractedField(value=None, confidence=0.0)

    def _extract_destination(self, handling_section: str) -> ExtractedField:
        """
        Extract destination airport code (arrival point).
        Must be exactly 3 uppercase letters (IATA code).
        """
        if not handling_section or len(handling_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=handling_section,
            field_name="DESTINATION AIRPORT",
            instructions=[
                "Find the 3-letter IATA airport code for ARRIVAL point",
                "MUST be exactly 3 uppercase letters",
                "Common codes: JFK (New York), LAX (Los Angeles), LHR (London), CDG (Paris)",
                "Return ONLY the 3-letter code, nothing else",
                "Return null if no valid 3-letter code found"
            ]
        )
        
        field = self._call_llm_field_extraction(prompt, "destination")
        
        # Validate it's exactly 3 letters
        if field.value and len(field.value) == 3 and field.value.isupper():
            return field
        
        return ExtractedField(value=None, confidence=0.0)

    def _extract_pieces(self, cargo_section: str) -> ExtractedField:
        """
        Extract number of pieces/packages.
        Must be an integer.
        """
        if not cargo_section or len(cargo_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=cargo_section,
            field_name="PIECES",
            instructions=[
                "Extract the NUMBER OF PIECES or packages",
                "Must be a whole number (integer)",
                "Look for labels like 'pieces', 'pcs', 'packages', 'pallets', 'items'",
                "Return ONLY the number as a string",
                "Return null if not found or unclear"
            ],
            examples={
                "No. of pieces: 5": "5",
                "Total packages: 12 boxes": "12",
                "PCS: 100": "100"
            }
        )
        
        field = self._call_llm_field_extraction(prompt, "pieces")
        
        # Validate it's a valid integer
        if field.value:
            try:
                int(field.value)
                return field
            except ValueError:
                pass
        
        return ExtractedField(value=None, confidence=0.0)

    def _extract_weight(self, cargo_section: str) -> ExtractedField:
        """
        Extract gross weight in kilograms.
        Can be integer or decimal (handle comma as decimal separator).
        """
        if not cargo_section or len(cargo_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=cargo_section,
            field_name="WEIGHT",
            instructions=[
                "Extract the GROSS WEIGHT of the entire shipment",
                "Must be in KILOGRAMS",
                "Can be whole number or decimal",
                "If you see comma as decimal separator (e.g., '1500,5'), convert to '1500.5'",
                "Look for labels like 'gross weight', 'wt', 'kg', 'gwt', 'total weight'",
                "Return ONLY the number as a string (using dot as decimal separator)",
                "Return null if not found"
            ],
            examples={
                "Gross Weight: 500 kg": "500",
                "Weight: 1500,5 KG": "1500.5",
                "GWT: 2000": "2000"
            }
        )
        
        field = self._call_llm_field_extraction(prompt, "weight")
        
        # Validate it's a valid number
        if field.value:
            try:
                float(field.value)
                return field
            except ValueError:
                pass
        
        return ExtractedField(value=None, confidence=0.0)

    def _extract_goods_description(self, cargo_section: str) -> ExtractedField:
        """Extract short description of goods being shipped."""
        if not cargo_section or len(cargo_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=cargo_section,
            field_name="GOODS DESCRIPTION",
            instructions=[
                "Extract a SHORT description of what is being shipped",
                "Look for labels like 'description', 'contents', 'said to contain', 'merci'",
                "Keep it brief (max 50 words)",
                "Do NOT copy entire cargo manifests or detailed lists",
                "Return a concise summary",
                "Return null if not found"
            ],
            examples={
                "Electronic components - CPU, RAM, SSD": "Electronic components",
                "Automotive spare parts and accessories": "Automotive spare parts",
                "Fashion items: T-shirts, jeans, jackets": "Fashion items"
            }
        )
        
        return self._call_llm_field_extraction(prompt, "goods_description")

    def _extract_flight_number(self, handling_section: str) -> ExtractedField:
        """
        Extract flight number (airline code + number).
        Format: e.g., CP137, LH2054, BA285
        """
        if not handling_section or len(handling_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=handling_section,
            field_name="FLIGHT NUMBER",
            instructions=[
                "Extract the FLIGHT NUMBER from the handling section",
                "Format is usually airline code (2-3 letters) + numeric code",
                "Examples: CP137, LH2054, BA285, UA456",
                "Look for label 'flight', 'flight no', 'flight number'",
                "Return ONLY the flight code and number",
                "Return null if not found"
            ],
            examples={
                "Flight: CP 137": "CP137",
                "FLIGHT NO: LH-2054": "LH2054",
                "Flight number BA 285": "BA285"
            }
        )
        
        return self._call_llm_field_extraction(prompt, "flight_number")

    def _extract_flight_date(self, handling_section: str) -> ExtractedField:
        """
        Extract flight departure date.
        Should be in YYYY-MM-DD format.
        """
        if not handling_section or len(handling_section) < 5:
            return ExtractedField(value=None, confidence=0.0)
        
        prompt = self._build_prompt(
            section_text=handling_section,
            field_name="FLIGHT DATE",
            instructions=[
                "Extract the FLIGHT DEPARTURE DATE",
                "Look for label 'date', 'flight date', 'departure date', 'data volo'",
                "Convert any date format to YYYY-MM-DD",
                "Examples: '15/03/2024' → '2024-03-15', 'March 15, 2024' → '2024-03-15'",
                "Return ONLY the date in YYYY-MM-DD format",
                "Return null if date cannot be parsed or not found"
            ]
        )
        
        return self._call_llm_field_extraction(prompt, "flight_date")

    def _build_prompt(
        self,
        section_text: str,
        field_name: str,
        instructions: List[str],
        examples: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build a structured prompt for field extraction.
        
        Args:
            section_text: The specific section text to analyze
            field_name: The field we're extracting
            instructions: List of specific instructions for extraction
            examples: Dict of example input → output for few-shot learning
            
        Returns:
            Complete prompt string
        """
        prompt = f"""You are an expert Air Waybill (AWB) parser. Your task is to extract ONE SPECIFIC FIELD.

FIELD TO EXTRACT: {field_name}

INSTRUCTIONS:
"""
        for i, instr in enumerate(instructions, 1):
            prompt += f"{i}. {instr}\n"
        
        if examples:
            prompt += "\nFEW-SHOT EXAMPLES:\n"
            for input_text, output_value in examples.items():
                prompt += f"Input: {input_text}\nOutput: {output_value}\n"
        
        prompt += f"""
SECTION TEXT TO ANALYZE:
{section_text}

EXTRACTION TASK:
Extract the {field_name} from the above section text.
Return ONLY a valid JSON object with these fields:
{{
  "value": <extracted_value_or_null>,
  "confidence": <confidence_score_0_to_1>,
  "reasoning": "<brief_explanation>"
}}

CRITICAL RULES:
- Return ONLY valid JSON, no explanations
- If you cannot confidently extract the field, set "value": null
- Be strict about format requirements mentioned in instructions
- Do not make assumptions or guess

JSON:
"""
        return prompt

    def _call_llm_field_extraction(self, prompt: str, field_name: str) -> ExtractedField:
        """
        Call LLM with field extraction prompt and parse response.
        
        Args:
            prompt: The extraction prompt
            field_name: Name of field being extracted (for debugging)
            
        Returns:
            ExtractedField with value, confidence, and metadata
        """
        try:
            # Call LLM
            llm_response = self.llm.extract_awb_json(prompt)
            
            # Parse JSON response
            result = json.loads(llm_response)
            
            return ExtractedField(
                value=result.get('value'),
                confidence=result.get('confidence', 0.0),
                source_section=field_name,
                reasoning=result.get('reasoning', '')
            )
        
        except json.JSONDecodeError as e:
            # If LLM response is not valid JSON, try to extract value from text
            print(f"JSON parsing error for {field_name}: {e}")
            print(f"LLM response: {llm_response[:100]}")
            return ExtractedField(value=None, confidence=0.0)
        
        except Exception as e:
            print(f"LLM extraction error for {field_name}: {e}")
            return ExtractedField(value=None, confidence=0.0)
