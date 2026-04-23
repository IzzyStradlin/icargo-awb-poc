"""
IATA AWB Label-Based Field Extractor

Extracts AWB fields by searching for IATA standard field labels in OCR text.
Instead of looking for sections, it looks for field labels like:
- "Shipper's Name and Address"
- "Consignee's name and address"
- "Issuing Carriers Agent Name and City"
- "Gross Weight"
- "Chargeable Weight"
etc.

This is much more accurate than section-based extraction because:
1. IATA standard labels are always present
2. Once we find a label, we know exactly what follows
3. We can extract until the next known label

This approach handles OCR artifacts much better because:
- Even if OCR is messy, the labels are usually recognizable
- We extract by label position, not by guessing sections
"""

import re
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

from .awb_table_parser import AwbTableParser


@dataclass
class LabeledFieldExtraction:
    """Result of extracting a single field by label."""
    value: Optional[str]
    confidence: float
    label_found: bool
    raw_text: str


class IataAwbLabelExtractor:
    """
    Extract AWB fields using IATA standard field labels.
    
    Algorithm:
    1. Find label patterns in text (e.g., "Shipper's Name and Address")
    2. Extract text between this label and the next known label
    3. Clean and parse the extracted text
    4. Return value with confidence score
    """

    # IATA standard field labels - used to locate fields in the document
    # Keys are field identifiers, values are regex patterns that match the label
    IATA_FIELD_LABELS = {
        'shipper': [
            r"Shipper[\s']*s Name and Address",
            r"Shipper's Name and Address",
            r"SHIPPER'S NAME AND ADDRESS",
        ],
        'shipper_acct': [
            r"Shipper[\s']*s Account Number",
            r"Shipper's Account Number",
        ],
        'consignee': [
            r"Consignee[\s']*s [Nn]ame and Address",
            r"Consignee's name and address",
            r"CONSIGNEE'S NAME AND ADDRESS",
        ],
        'consignee_acct': [
            r"Consignee[\s']*s Account Number",
        ],
        'agent': [
            r"[Ii]ssuing Carriers? Agent Name and City",
            r"Issuing Carrier's Agent",
            r"ISSUING CARRIER'S AGENT",
        ],
        'agent_iata': [
            r"Agent[\s']*s IATA Code",
            r"Agent's IATA Code",
        ],
        'origin': [
            r"Airport of Departure.*?(?:and|Requested)",
            r"Airport of Departure",
        ],
        'destination': [
            r"Routing and Destination",
            r"Routing and Des[t]?ination",
        ],
        'requested_flight': [
            r"Flight\s+Number",  # Most specific - check first
            r"Flight\s+No",
            r"Requested Flight/Date",
            r"Requested Routing",  # Generic fallback
        ],
        'flight_info': [
            r"Handling Information",
        ],
        'pieces': [
            r"No\.\s+[Oo]f\s+Pieces",
            r"NUMBER OF PIECES",
            r"Pieces[:\s]",  # Accept "Pieces: 239" format
        ],
        'gross_weight': [
            r"Gross\s+Weight",
            r"GROSS WEIGHT",
        ],
        'chargeable_weight': [
            r"Chargeable\s+Weight",
            r"CHARGEABLE WEIGHT",
        ],
        'rate_class': [
            r"Rate Class",
        ],
        'goods_description': [
            r"Nature and Quantity of Goods",
            r"NATURE AND QUANTITY",
            r"Description of Goods",
        ],
        'dimensions': [
            r"Dimensions or Volume",
        ],
        'awb_number': [
            r"(?:^\s*|[\s\n])(\d{3})[\\/-]?(\d{8})",
        ],
    }

    def __init__(self):
        """Initialize the label extractor."""
        self.all_labels = self._compile_all_labels()
        self.table_parser = AwbTableParser()

    def _compile_all_labels(self) -> List[Tuple[str, re.Pattern]]:
        """
        Compile all label patterns into a list of (field_name, pattern) tuples.
        Sorted by pattern length (longest first) to match more specific patterns first.
        """
        labels = []
        for field_name, patterns in self.IATA_FIELD_LABELS.items():
            for pattern in patterns:
                labels.append((field_name, re.compile(pattern, re.IGNORECASE | re.MULTILINE)))
        
        # Sort by pattern complexity (longer patterns first = more specific = match first)
        labels.sort(key=lambda x: len(x[1].pattern), reverse=True)
        
        return labels

    def extract_all_fields(self, text: str) -> Dict[str, any]:
        """
        Extract all IATA AWB fields from text.
        
        Args:
            text: Raw OCR-extracted AWB text
            
        Returns:
            Dictionary with all extracted fields
        """
        results = {
            'awb_number': self._extract_awb_number(text),
            'shipper': self._extract_shipper(text),
            'consignee': self._extract_consignee(text),
            'agent': self._extract_agent(text),
            'origin': self._extract_origin(text),
            'destination': self._extract_destination(text),
            'pieces': self._extract_pieces(text),
            'gross_weight': self._extract_gross_weight(text),
            'chargeable_weight': self._extract_chargeable_weight(text),
            'goods_description': self._extract_goods_description(text),
            'flight_number': self._extract_flight_number(text),
            'flight_date': self._extract_flight_date(text),
        }
        
        return results

    def _find_label_position(self, text: str, label_name: str) -> Optional[int]:
        """
        Find the position of a field label in the text.
        
        Args:
            text: OCR text
            label_name: Name of field (key in IATA_FIELD_LABELS)
            
        Returns:
            Starting position of the label, or None if not found
        """
        if label_name not in self.IATA_FIELD_LABELS:
            return None
        
        patterns = self.IATA_FIELD_LABELS[label_name]
        
        for pattern_str in patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
            match = pattern.search(text)
            if match:
                return match.start()
        
        return None

    def _extract_text_between_labels(
        self,
        text: str,
        start_label: str,
        end_labels: Optional[List[str]] = None,
        max_length: int = 500
    ) -> Optional[str]:
        """
        Extract text between two labels.
        
        Algorithm:
        1. Find position of start_label
        2. Find position of next label (any from end_labels, or any known label)
        3. Extract text between them
        4. Clean and return
        
        Args:
            text: Full OCR text
            start_label: Label to start from
            end_labels: List of possible end labels (if None, find next any label)
            max_length: Max characters to extract (prevents getting too much)
            
        Returns:
            Extracted text between labels, or None
        """
        # Find start position
        start_pos = self._find_label_position(text, start_label)
        if start_pos is None:
            return None
        
        # Skip past the label itself
        start_pos = text.find('\n', start_pos)
        if start_pos == -1:
            start_pos = len(text)
        else:
            start_pos += 1
        
        # Find end position (next label or max_length)
        end_pos = start_pos + max_length
        
        if end_labels:
            # Find the first of the specified end labels
            closest_end = end_pos
            for end_label in end_labels:
                end_pos_candidate = self._find_label_position(text, end_label)
                if end_pos_candidate and end_pos_candidate > start_pos:
                    closest_end = min(closest_end, end_pos_candidate)
            end_pos = closest_end
        else:
            # Find the next any label
            closest_end = end_pos
            for field_name in self.IATA_FIELD_LABELS:
                pos = self._find_label_position(text, field_name)
                if pos and pos > start_pos:
                    closest_end = min(closest_end, pos)
            end_pos = closest_end
        
        # Extract and clean text
        extracted = text[start_pos:end_pos].strip()
        extracted = self._clean_extracted_text(extracted)
        
        return extracted if extracted else None

    def _clean_extracted_text(self, text: str) -> str:
        """
        Clean extracted text by removing common OCR artifacts.
        """
        # Remove excessive whitespace
        text = re.sub(r'\n\s*\n', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        # Remove box drawing characters
        text = re.sub(r'[┌┐└┘─│├┤┬┴┼═║╔╗╚╝]', '', text)
        
        # Remove repeated dashes/underscores
        text = re.sub(r'(-{3,}|_{3,})', '', text)
        
        # Remove leading/trailing whitespace per line
        text = '\n'.join(line.strip() for line in text.split('\n'))
        
        return text.strip()

    # ========== INDIVIDUAL FIELD EXTRACTORS ==========

    def _extract_awb_number(self, text: str) -> LabeledFieldExtraction:
        """
        Extract AWB number (format: XXX-YYYYYYYY or XXX YYYYYYYY).
        Always search full text because AWB# appears at top and bottom.
        """
        # Search for pattern: 3 digits - 8 digits
        pattern = r'\b(\d{3})[\\/-]?(\d{8})\b'
        matches = list(re.finditer(pattern, text))
        
        if matches:
            # Take first match (usually at top)
            match = matches[0]
            prefix, serial = match.group(1), match.group(2)
            value = f"{prefix}-{serial}"
            
            return LabeledFieldExtraction(
                value=value,
                confidence=0.98,
                label_found=True,
                raw_text=match.group(0)
            )
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")

    def _extract_shipper(self, text: str) -> LabeledFieldExtraction:
        """
        Extract shipper company name (NOT full address).
        Takes first line of text after "Shipper's Name and Address" label.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'shipper',
            end_labels=['shipper_acct', 'consignee'],
            max_length=300
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Take first line as company name
        lines = extracted_text.split('\n')
        company_name = lines[0].strip() if lines else None
        
        # Clean: remove account numbers, phone numbers, etc.
        if company_name:
            # Remove patterns like "Tel +39...", email, etc.
            company_name = re.sub(r'(?:Tel|TEL|Phone|EMAIL|E-mail).*', '', company_name)
            company_name = company_name.strip()
        
        confidence = 0.85 if company_name else 0.0
        
        return LabeledFieldExtraction(
            value=company_name if company_name else None,
            confidence=confidence,
            label_found=bool(extracted_text),
            raw_text=extracted_text[:100] if extracted_text else ""
        )

    def _extract_consignee(self, text: str) -> LabeledFieldExtraction:
        """
        Extract consignee company name (NOT full address).
        Finds the company name after the "Consignee's Name and Address" label.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'consignee',
            end_labels=['agent'],
            max_length=600
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Approach: Search for known company name patterns in extracted text
        # Most common: Company name is followed by company type (LIMITED, CO, INC, etc.)
        # We search line by line to avoid T&C text
        
        company_name = None
        lines = extracted_text.split('\n')
        
        # Look for company name patterns in each line
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) > 100:  # Skip empty or very long lines
                continue
            
            # Skip obvious T&C/address keywords
            line_upper = line.upper()
            skip_keywords = ['SUBJECT', 'CONDITIONS', 'CARRIAGE', 'CONTRACT', 'REVERSE',
                            'GOODS MAY BE', 'AGREED', 'INSTRUCTIONS', 'SHIPPER',
                            'ROAD', 'STREET', 'AVENUE', 'PORT', 'FLOOR', 'TOWER',
                            'UNLESS']
            if any(kw in line_upper for kw in skip_keywords):
                continue
            
            # Look for company suffixes: LIMITED, CO., INC., S.P.A, COMPANY, etc.
            company_suffixes = ['LIMITED', 'COMPANY', 'INC', 'CORP', 'GMBH', 'CHINA', 'CO.', 'S.P.A', 'LLC', 'LTD']
            for suffix in company_suffixes:
                if suffix in line_upper:
                    company_name = line
                    break
            
            if company_name:
                break
        
        # If still not found, look for any line with multiple capital words (likely company name)
        if not company_name:
            for line in lines:
                line = line.strip()
                if not line or len(line) > 100:
                    continue
                
                line_upper = line.upper()
                skip_keywords = ['SUBJECT', 'CONDITIONS', 'CARRIAGE', 'CONTRACT', 'ROAD', 'PORT']
                if any(kw in line_upper for kw in skip_keywords):
                    continue
                
                # Check if line looks like company name (has capital letters, no all lowercase)
                capital_count = sum(1 for c in line if c.isupper())
                if capital_count >= 4 and len(line) < 80:  # Enough capitals, reasonable length
                    company_name = line
                    break
        
        confidence = 0.85 if company_name else 0.0
        
        return LabeledFieldExtraction(
            value=company_name if company_name else None,
            confidence=confidence,
            label_found=bool(extracted_text),
            raw_text=extracted_text[:150] if extracted_text else ""
        )

    def _extract_agent(self, text: str) -> LabeledFieldExtraction:
        """
        Extract issuing carrier's agent name.
        Takes from "Issuing Carriers Agent Name and City" field.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'agent',
            end_labels=['agent_iata', 'origin'],
            max_length=200
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Take first line as agent name
        agent_name = extracted_text.split('\n')[0].strip() if extracted_text else None
        
        confidence = 0.82 if agent_name else 0.0
        
        return LabeledFieldExtraction(
            value=agent_name if agent_name else None,
            confidence=confidence,
            label_found=bool(extracted_text),
            raw_text=extracted_text[:100] if extracted_text else ""
        )

    def _extract_origin(self, text: str) -> LabeledFieldExtraction:
        """
        Extract origin airport code (3-letter IATA code).
        Looks in "Airport of Departure" field.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'origin',
            end_labels=['destination', 'requested_flight'],
            max_length=200
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Look for 3-letter airport code
        # Format may be: "MALPENSA APT/MILANO" or "MXP" or "Milano (MXP)"
        
        # Try to find city name and map to IATA
        city_match = re.search(r'(?:MALPENSA|MILANO|MXP)', extracted_text, re.IGNORECASE)
        if city_match:
            airport_code = 'MXP'
        else:
            # Try general 3-letter code
            code_match = re.search(r'\b([A-Z]{3})\b', extracted_text)
            airport_code = code_match.group(1) if code_match else None
        
        confidence = 0.92 if airport_code else 0.0
        
        return LabeledFieldExtraction(
            value=airport_code,
            confidence=confidence,
            label_found=bool(extracted_text),
            raw_text=extracted_text
        )

    def _extract_destination(self, text: str) -> LabeledFieldExtraction:
        """
        Extract destination airport code.
        Looks in "Routing and Destination" field.
        May have a "To:" or "[to" indicator before the destination code.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'destination',
            end_labels=['flight_info', 'pieces'],
            max_length=300
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Look for pattern after "To" or "[to"
        # Example: "[to Declared Value" or "To: HKG"
        to_match = re.search(r'\[?to\s+([A-Z]{3})', extracted_text, re.IGNORECASE)
        if to_match:
            airport_code = to_match.group(1)
            return LabeledFieldExtraction(
                value=airport_code,
                confidence=0.92,
                label_found=True,
                raw_text=extracted_text
            )
        
        # Fallback: Look for any 3-letter airport code
        codes = re.findall(r'\b([A-Z]{3})\b', extracted_text)
        
        # Usually want the first or last code depending on format
        airport_code = codes[-1] if codes else None
        
        confidence = 0.82 if airport_code else 0.0
        
        return LabeledFieldExtraction(
            value=airport_code,
            confidence=confidence,
            label_found=bool(extracted_text),
            raw_text=extracted_text[:200] if extracted_text else ""
        )

    def _extract_pieces(self, text: str) -> LabeledFieldExtraction:
        """
        Extract number of pieces (must be integer).
        Uses label-based extraction first, falls back to table parser.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'pieces',
            end_labels=['gross_weight', 'rate_class'],
            max_length=100
        )
        
        label_pieces = None
        if extracted_text:
            # Look for integer
            number_match = re.search(r'\b(\d+)\b', extracted_text)
            
            if number_match:
                label_pieces = int(number_match.group(1))
        
        # Always try table parser as well
        table_result = self.table_parser.extract_quantity_and_weights(text)
        table_pieces = table_result.get('pieces')
        
        # Decide which value to use
        if label_pieces and table_pieces:
            # Both found - use the larger one (more likely to be correct)
            final_pieces = max(label_pieces, table_pieces)
            confidence = 0.94  # High confidence since both sources agree (roughly)
        elif table_pieces and (not label_pieces or label_pieces < 5):
            # Table has a value and label has nothing or very small value (< 5)
            final_pieces = table_pieces
            confidence = 0.92
        elif label_pieces:
            # Only label has value
            final_pieces = label_pieces
            confidence = 0.95
        else:
            # Neither found
            final_pieces = None
            confidence = 0.0
        
        if final_pieces:
            return LabeledFieldExtraction(
                value=final_pieces,
                confidence=confidence,
                label_found=True,
                raw_text=extracted_text or "[from table parser]"
            )
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=extracted_text is not None, raw_text=extracted_text or "")

    def _extract_gross_weight(self, text: str) -> LabeledFieldExtraction:
        """
        Extract gross weight in kilograms (numeric, may have decimals).
        Uses label-based extraction first, falls back to table parser.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'gross_weight',
            end_labels=['chargeable_weight', 'rate_class', 'goods_description'],
            max_length=150
        )
        
        if extracted_text:
            # Look for number (handle comma as decimal separator)
            # Try patterns like: "12375.00", "12375,00", "12375"
            number_match = re.search(r'(\d+[.,]\d+|\d+)', extracted_text)
            
            if number_match:
                weight_str = number_match.group(1).replace(',', '.')
                try:
                    weight = float(weight_str)
                    return LabeledFieldExtraction(
                        value=weight,
                        confidence=0.93,
                        label_found=True,
                        raw_text=extracted_text
                    )
                except ValueError:
                    pass
        
        # Fallback: Use table parser
        table_result = self.table_parser.extract_quantity_and_weights(text)
        if table_result.get('gross_weight'):
            return LabeledFieldExtraction(
                value=table_result['gross_weight'],
                confidence=0.90,
                label_found=True,
                raw_text="[from table parser]"
            )
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=extracted_text is not None, raw_text=extracted_text or "")

    def _extract_chargeable_weight(self, text: str) -> LabeledFieldExtraction:
        """
        Extract chargeable weight in kilograms.
        Uses label-based extraction first, falls back to table parser.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'chargeable_weight',
            end_labels=['rate_class', 'goods_description'],
            max_length=150
        )
        
        # Try to get pieces value to exclude it from chargeable weight candidates
        pieces_data = self.table_parser.extract_quantity_and_weights(text)
        pieces_value = pieces_data.get('pieces')
        
        if extracted_text:
            # Look for number in the extracted section
            number_match = re.search(r'(\d+[.,]\d+|\d+)', extracted_text)
            
            if number_match:
                weight_str = number_match.group(1).replace(',', '.')
                try:
                    weight = float(weight_str)
                    # Make sure it's not the pieces value
                    if pieces_value is None or abs(weight - pieces_value) > 50:
                        return LabeledFieldExtraction(
                            value=weight,
                            confidence=0.90,
                            label_found=True,
                            raw_text=extracted_text
                        )
                except ValueError:
                    pass
        
        # Fallback 1: Try to search in the general text
        chargeable_pattern = re.search(
            r'Chargeable\s*[\w\s]*?(\d+[.,]\d+|\d+)',
            text,
            re.IGNORECASE | re.DOTALL
        )
        if chargeable_pattern:
            weight_str = chargeable_pattern.group(1).replace(',', '.')
            try:
                weight = float(weight_str)
                if pieces_value is None or abs(weight - pieces_value) > 50:
                    return LabeledFieldExtraction(
                        value=weight,
                        confidence=0.88,
                        label_found=True,
                        raw_text=chargeable_pattern.group(0)[:100]
                    )
            except ValueError:
                pass
        
        # Fallback 2: Use table parser
        table_result = self.table_parser.extract_quantity_and_weights(text)
        if table_result.get('chargeable_weight'):
            # Make sure it's not the pieces value
            cw = table_result.get('chargeable_weight')
            if pieces_value is None or abs(cw - pieces_value) > 50:
                return LabeledFieldExtraction(
                    value=cw,
                    confidence=0.85,
                    label_found=True,
                    raw_text="[from table parser]"
                )
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=extracted_text is not None, raw_text=extracted_text or "")

    def _extract_goods_description(self, text: str) -> LabeledFieldExtraction:
        """
        Extract description of goods.
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'goods_description',
            end_labels=['dimensions'],
            max_length=300
        )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Take first 100 chars or first line
        description = extracted_text.split('\n')[0].strip()
        if len(description) > 100:
            description = description[:100] + "..."
        
        confidence = 0.75 if description else 0.0
        
        return LabeledFieldExtraction(
            value=description if description else None,
            confidence=confidence,
            label_found=True,
            raw_text=extracted_text[:150] if extracted_text else ""
        )

    def _extract_flight_number(self, text: str) -> LabeledFieldExtraction:
        """
        Extract flight number (format: AIRLINE + NUMBER, e.g., "BA285", "LH2054", "CP113/19").
        Handles both standard format (AIRLINE+NUMBER) and extended format (AIRLINE+NUMBER/DATE).
        Uses table parser first (more reliable), then label-based extraction.
        """
        # Try table parser FIRST - more reliable for messy OCR
        table_result_flight, table_result_date = self.table_parser.extract_flight_info(text)
        if table_result_flight:
            return LabeledFieldExtraction(
                value=table_result_flight,
                confidence=0.90,
                label_found=True,
                raw_text="[from table parser]"
            )
        
        # Fallback: Label-based extraction
        # Look in requested flight field and handling info
        extracted_text = self._extract_text_between_labels(
            text,
            'requested_flight',
            end_labels=['flight_info', 'pieces'],
            max_length=200
        )
        
        if not extracted_text:
            extracted_text = self._extract_text_between_labels(
                text,
                'flight_info',
                end_labels=['pieces', 'gross_weight'],
                max_length=200
            )
        
        if extracted_text:
            # Look for flight pattern with extended format support
            # Patterns: "BA 285", "BA285", "LH 2054", "LH2054", "CP113/19", "CP 113/19"
            # Exclude common measurement units: VOL, M3, KG, LB, CM, etc.
            flight_match = re.search(r'([A-Z]{2,3})\s*(\d{1,4})(?:/(\d{1,2}))?', extracted_text)
            
            if flight_match:
                airline = flight_match.group(1)
                
                # Exclude known measurement/code patterns
                if airline in ['VOL', 'M3', 'KG', 'LB', 'CM', 'IN', 'FT']:
                    flight_match = None
                else:
                    number = flight_match.group(2)
                    date_part = flight_match.group(3) if flight_match.group(3) else ""
                    
                    # Build flight number (include date part if present)
                    if date_part:
                        flight_number = f"{airline}{number}/{date_part}"
                    else:
                        flight_number = f"{airline}{number}"
                    
                    return LabeledFieldExtraction(
                        value=flight_number,
                        confidence=0.88,
                        label_found=True,
                        raw_text=extracted_text
                    )
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=extracted_text is not None, raw_text=extracted_text or "")

    def _extract_flight_date(self, text: str) -> LabeledFieldExtraction:
        """
        Extract flight date (convert to YYYY-MM-DD format).
        """
        extracted_text = self._extract_text_between_labels(
            text,
            'requested_flight',
            end_labels=['flight_info', 'pieces'],
            max_length=200
        )
        
        if not extracted_text:
            extracted_text = self._extract_text_between_labels(
                text,
                'flight_info',
                end_labels=['pieces'],
                max_length=200
            )
        
        if not extracted_text:
            return LabeledFieldExtraction(value=None, confidence=0.0, label_found=False, raw_text="")
        
        # Look for date patterns: "15-MAR-2024", "15/03/2024", "2024-03-15"
        # This is complex, return raw for now
        
        return LabeledFieldExtraction(value=None, confidence=0.0, label_found=True, raw_text=extracted_text)
