# app/interpretation/awb_field_detector.py
import re
from typing import List, Dict, Any, Optional
from .awb_schema import AwbData, AwbFieldConfidence, AwbExtractionResult

AWB_PATTERN = re.compile(r"\b(\d{3})[-\s]?(\d{8})\b")
COMMON_IATA = {
    'MXP', 'FCO', 'HKG', 'JFK', 'LAX', 'LHR', 'CDG', 'AMS', 'FRA', 'ZRH',
    'MAD', 'BCN', 'MUC', 'VCE', 'BUD', 'PRG', 'WAW', 'KRK', 'LIN', 'BGY',
    'TRN', 'TFS', 'PSA', 'PER', 'IVR', 'NAP', 'CIA', 'BRI', 'BLQ',
    'MSE', 'BVA', 'ORY', 'EWR', 'LGA', 'SFO', 'LAX', 'SEA',
    'YVR', 'YYZ', 'SYD', 'MEL', 'BKK', 'SIN', 'NRT', 'HND', 'ICN', 'PEK',
    'DXB', 'AUH', 'KUL', 'CGK', 'GRU', 'MEX', 'SCL'
}

# Map city/airport names to IATA codes
CITY_TO_IATA = {
    'MILANO': 'MXP',
    'MALPENSA': 'MXP',
    'ROME': 'FCO',
    'ROMA': 'FCO',
    'HONG KONG': 'HKG',
    'HONGKONG': 'HKG',
    'LIMA': 'LIM',
    'NEW YORK': 'JFK',
    'LOS ANGELES': 'LAX',
    'LONDON': 'LHR',
    'PARIS': 'CDG',
    'AMSTERDAM': 'AMS',
    'FRANKFURT': 'FRA',
    'ZURICH': 'ZRH',
    'MADRID': 'MAD',
    'BARCELONA': 'BCN',
    'MUNICH': 'MUC',
    'VENICE': 'VCE',
    'BUDAPEST': 'BUD',
    'PRAGUE': 'PRG',
    'WARSAW': 'WAW',
    'KRAKOW': 'KRK',
    'TURIN': 'TRN',
    'PISA': 'PSA',
    'BUENOS AIRES': 'GRU',
    'MEXICO': 'MEX',
    'SANTIAGO': 'SCL',
    'DUBAI': 'DXB',
    'ABU DHABI': 'AUH',
    'KUALA LUMPUR': 'KUL',
    'BANGKOK': 'BKK',
    'SINGAPORE': 'SIN',
    'TOKYO': 'NRT',
    'SEOUL': 'ICN',
    'BEIJING': 'PEK',
    'SYDNEY': 'SYD',
    'MELBOURNE': 'MEL',
}

class AwbFieldDetector:
    """Section-aware rule-based AWB field extractor."""

    def extract(self, text: str, sections: Optional[Dict[str, str]] = None) -> AwbExtractionResult:
        """
        Extract AWB fields from text.
        If sections dict is provided, use section-specific extraction (more accurate).
        Otherwise, use regex on full text (fallback).
        """
        data = AwbData()
        confidences: List[AwbFieldConfidence] = []
        
        # Use sections if available, otherwise use full text
        sections = sections or self._fallback_sections(text)

        # AWB number - from full text (always present)
        m = AWB_PATTERN.search(text)
        if m:
            data.awb_prefix, data.awb_serial = m.group(1), m.group(2)
            confidences.append(AwbFieldConfidence(field="awb_number", value=f"{data.awb_prefix}-{data.awb_serial}", confidence=0.95))

        # Origin/Destination - section-aware
        origin, dest = self._extract_origin_destination(text, sections)
        if origin:
            data.origin = origin
            confidences.append(AwbFieldConfidence(field="origin", value=data.origin, confidence=0.95))
        if dest:
            data.destination = dest
            confidences.append(AwbFieldConfidence(field="destination", value=data.destination, confidence=0.95))

        # Pieces - from full text or cargo section
        pieces_val = self._extract_pieces(text, sections)
        if pieces_val:
            data.pieces = pieces_val
            confidences.append(AwbFieldConfidence(field="pieces", value=str(data.pieces), confidence=0.85))
        
        # Weight - from full text or cargo section
        weight_val = self._extract_weight(text, sections)
        if weight_val:
            data.weight = weight_val
            confidences.append(AwbFieldConfidence(field="weight", value=str(data.weight), confidence=0.9))

        # Shipper - from shipper section
        shipper_section = (sections or {}).get('shipper', '')
        shipper_val = self._extract_shipper(shipper_section or text)
        if shipper_val:
            data.shipper = shipper_val
            confidences.append(AwbFieldConfidence(field="shipper", value=data.shipper, confidence=0.92))
        
        # Consignee - from consignee section
        consignee_section = (sections or {}).get('consignee', '')
        consignee_val = self._extract_consignee(consignee_section or text, shipper=shipper_val)
        if consignee_val:
            data.consignee = consignee_val
            confidences.append(AwbFieldConfidence(field="consignee", value=data.consignee, confidence=0.75))

        # Flight number - from handling section or full text
        handling_section = (sections or {}).get('handling', '')
        flight_val = self._extract_flight_number(handling_section or text)
        if flight_val:
            data.flight_no = flight_val
            confidences.append(AwbFieldConfidence(field="flight_number", value=data.flight_no, confidence=0.88))

        # Flight date - from handling section or full text
        date_val = self._extract_flight_date(handling_section or text)
        if date_val:
            data.flight_date = date_val
            confidences.append(AwbFieldConfidence(field="flight_date", value=data.flight_date, confidence=0.75))

        # Agent = shipper (customer)
        if data.shipper:
            data.agent = data.shipper
            confidences.append(AwbFieldConfidence(field="agent", value=data.agent, confidence=0.92))

        # Goods description - from cargo section
        cargo_section = (sections or {}).get('cargo', '')
        goods_val = self._extract_goods_description(cargo_section or text)
        if goods_val:
            data.goods_description = goods_val
            confidences.append(AwbFieldConfidence(field="goods_description", value=data.goods_description, confidence=0.7))

        return AwbExtractionResult(data=data, confidences=confidences, raw_text=text)

    def _fallback_sections(self, text: str) -> Dict[str, str]:
        """Create minimal sections from flat text for backward compatibility."""
        return {
            'shipper': text,
            'consignee': text,
            'agent': text,
            'handling': text,
            'cargo': text,
            'customs': text,
            'full_text': text,
        }

    def _extract_origin_destination(self, text: str, sections: Dict[str, str]) -> tuple:
        """
        Extract origin and destination from full text.
        AWB forms have labels followed by possibly several lines of garbage/form data before actual value.
        Tries multiple patterns:
        1. Label with flexible gap handling (OCR-tolerant)
        2. City name mapping to IATA
        3. Fallback to IATA search
        """
        origin, dest = None, None
        
        # Phase 1: Extract with labels - use flexible patterns that handle OCR garbage between label and value
        # Pattern for origin: "Airport of Departure" followed by up to 8 lines of garbage, then city/code
        origin_patterns = [
            # Direct code on same/next line: "Airport of Departure: MXP" or "Departure MXP"
            r'Airport of Departure[^:]*:?[^\n]*\n(?:[^\n]*\n){0,3}?(\bMXP\b)',
            # City name: "MALPENSA" "MILANO"  
            r'Airport of Departure[^:]*:?[^\n]*\n(?:[^\n]*\n){0,8}?(MALPENSA|MILANO)',
            # Generic: any 3-letter code after departure label
            r'Departure[^:]*:?[^\n]*\n(?:[^\n]*\n){0,3}?([A-Z]{3}\b)',
            r'From[^:]*:?[^\n]*\n(?:[^\n]*\n){0,3}?([A-Z]{3})',
        ]
        
        for pattern in origin_patterns:
            origin_match = re.search(pattern, text, re.IGNORECASE)
            if origin_match:
                code_or_city = origin_match.group(1).strip().upper()
                # Check if it's already an IATA code
                if code_or_city in COMMON_IATA:
                    origin = code_or_city
                    break
                # Otherwise try to map city name to IATA
                if code_or_city in CITY_TO_IATA:
                    origin = CITY_TO_IATA[code_or_city]
                    break
        
        # Pattern 2: Destination with city/code mapping
        dest_patterns = [
            # Direct code: "To: HKG" or "Destination HKG"
            r'(?:Airport of Destination|To)[^:]*:?[^\n]*\n(?:[^\n]*\n){0,3}?(\bHKG\b)',
            # City name: "HONG KONG"
            r'(?:Airport of Destination|To)[^:]*:?[^\n]*\n(?:[^\n]*\n){0,8}?(HONG\s+KONG|HONGKONG)',
            # Generic 3-letter code
            r'(?:Destination|To)[^:]*:?[^\n]*\n(?:[^\n]*\n){0,3}?([A-Z]{3}\b)',
        ]
        
        for pattern in dest_patterns:
            dest_match = re.search(pattern, text, re.IGNORECASE)
            if dest_match:
                code_or_city = dest_match.group(1).strip().upper().replace(' ', '')
                # Check if it's already an IATA code
                if code_or_city in COMMON_IATA:
                    dest = code_or_city
                    break
                # Try to map city name to IATA
                if 'HONGKONG' in code_or_city or 'HONG' in code_or_city:
                    dest = 'HKG'
                    break
                if code_or_city in CITY_TO_IATA:
                    dest = CITY_TO_IATA[code_or_city]
                    break

        # Phase 2: Fallback to generic IATA search only if both origin and dest not found
        # BUT: only as LAST resort, and be smarter about order
        if not origin or not dest:
            iata_matches = []
            for iata in sorted(COMMON_IATA, key=len, reverse=True):
                for m in re.finditer(r'\b' + iata + r'\b', text, re.IGNORECASE):
                    iata_matches.append((m.start(), iata.upper()))
            
            iata_matches.sort(key=lambda x: x[0])
            iata_codes = []
            seen = set()
            for _, code in iata_matches:
                if code not in seen:
                    iata_codes.append(code)
                    seen.add(code)
            
            if not origin and len(iata_codes) >= 1:
                origin = iata_codes[0]
            if not dest and len(iata_codes) >= 2:
                dest = iata_codes[1]

        return origin, dest

    def _extract_pieces(self, text: str, sections: Dict[str, str]) -> Optional[int]:
        """Extract pieces from text. Handle various OCR formats."""
        # Try multiple patterns for pieces
        patterns = [
            r'(\d+)\s*[|/}]?\s*(?:pcs|pieces?|pc\b)',
            r'No\.\s*Of\s+Pieces[|:\s]+(\d+)',
            r'(?:Pieces?|PCS)[|:\s]+(\d+)',
            r'(\d+)\s*P(?:CS|ieces)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    pieces = int(match.group(1))
                    if pieces > 0:
                        return pieces
                except (ValueError, IndexError):
                    continue
        
        return None

    def _extract_weight(self, text: str, sections: Dict[str, str]) -> Optional[float]:
        """Extract weight from text. Handle various OCR formats."""
        # Multiple patterns for weight - OCR can produce different separators
        patterns = [
            # K Q format (manifest): "686.78K Q" or "1148.400/K}.Q" or "1148.400/KQ"
            r'(\d+(?:\.\d+)?)\s*[/]?\s*K[}.]?\s*Q',
            # Decimal with K: "1148.400/K}"
            r'(\d+(?:\.\d+)?)\s*[/}]?\s*K\b',
            # Weight with kg/KG suffix
            r'(\d+(?:\.\d+)?)\s*(?:kg|KG|KE|weight|wt)\b',
            # Labeled weight
            r'(?:weight|wt|Weight)\s*[:=]?\s*(\d+(?:\.\d+)?)',
            # Just before specific markers
            r'(\d+(?:\.\d+)?)\s*[/]?\s*(?:KG|kg)\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    weight_str = match.group(1).replace(',', '.')
                    weight = float(weight_str)
                    if weight > 0:
                        return weight
                except (ValueError, IndexError):
                    continue
        
        return None

    def _extract_shipper(self, text: str) -> Optional[str]:
        """Extract shipper from shipper section. Filter out city names and legal text."""
        # Multiple patterns to catch different formats
        patterns = [
            # Pattern 1: "Shipper's Name and Address" label followed by company name
            r'Shipper[\'s]*\s*(?:Name and Address)?[^\n]*\n+\s*([A-Z][A-Z0-9a-z\s\.&,\-]*?(?:S\.P\.A\.|Ltd|Inc|GmbH|SARL|SA|SRL|LTD|Co\.?|Corp|SPA|Ltd\.|Inc\.|L\.L\.C|LLC))\b',
            # Pattern 2: Starting from "Shipper" section, capture first line with company suffix
            r'Shipper[\'s]?[^\n]*\n+\s*([A-Z][A-Za-z0-9\s\.&,\-]{2,}?(?:S\.P\.A|Ltd|Inc|GmbH|SARL|SA|SRL))\s*(?:\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                shipper_text = match.group(1).strip()
                # Clean up
                shipper_text = shipper_text.split('\n')[0].strip()
                # Split on MSC to get only first company
                if 'MSC' in shipper_text.upper():
                    shipper_text = shipper_text.split('MSC')[0].strip()
                
                # Filter: reject if it's just a city name (MALPENSA, MILANO, etc) or legal text
                if (shipper_text.upper() not in ['MALPENSA', 'MILANO', 'ROMA', 'LONDON', 'PARIS', 'HONG KONG'] 
                    and len(shipper_text) > 3 and len(shipper_text) < 100
                    and not re.search(r'SUBJECT|CONDITIONS|SHIPMENT MAY|AGREED', shipper_text, re.IGNORECASE)):
                    return shipper_text
        
        return None

    def _extract_consignee(self, text: str, shipper: Optional[str] = None) -> Optional[str]:
        """Extract consignee from consignee section. Must NOT be carrier/agent or shipper."""
        # Carriers/agents to exclude
        carriers = ['MSC', 'ALISCARGO', 'LUFTHANSA', 'AIR FRANCE', 'KLM', 'BRITISH AIRWAYS', 'UNITED', 'DELTA']
        
        # Pattern: Specifically after "Consignee's Name and Address" label
        # Must be on the first real line after the label (not too many lines gap)
        patterns = [
            # After "Consignee's Name and Address": capture company name on first/next lines before legal text
            r'Consignee[\'s]*\s*(?:Name and Address)?[^\n]*\n+\s*([A-Z][A-Za-z0-9\s\.&,\(\)\-]{5,}?(?:Ltd|Inc|SRL|Corp|Co\.?|Company|GmbH|S\.A|S\.p\.A|LLC|LTD))\s*(?:\n|$)',
            # Alternative: with explicit section marker
            r'Consignee[\'s]*\s*Name and Address[^\n]*\n+\s*([A-Z][A-Za-z0-9\s\.&,\(\)-]{5,}?(?:Ltd|Inc|LTD|Ltd\.|Inc\.))\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                consignee_text = match.group(1).strip()
                consignee_text = consignee_text.split('\n')[0][:100].strip()
                
                # Filter out: carriers, agents, legal text, or if too short
                # CRITICAL: reject if it equals the shipper (likely extraction error matching wrong section)
                is_carrier = any(carrier.upper() in consignee_text.upper() for carrier in carriers)
                is_legal_text = re.search(r'SUBJECT|CONDITIONS|AGREED|CARRIED|SHIPPER|ISSUED', consignee_text, re.IGNORECASE)
                is_same_as_shipper = shipper and consignee_text.upper() == shipper.upper()
                
                if (consignee_text and len(consignee_text) > 5
                    and not is_carrier
                    and not is_legal_text
                    and not is_same_as_shipper):
                    return consignee_text
        
        return None

    def _extract_flight_number(self, text: str) -> Optional[str]:
        """Extract flight number. Handle OCR distortion with irregular spacing."""
        patterns = [
            # Standard: "CP125", "AZ123"
            r'(?:flight|flt|handling)\s*(?:no\.?|number|#|code)?\s*[:=]?\s*([A-Z]{2}\d{1,4})',
            # With slash: "CP125/16"
            r'([A-Z]{2}\d{1,4})/\d{1,2}',
            # From handling information section
            r'Handling\s+Information[^\n]*\n?[^\n]*([A-Z]{2}\d{1,4})',
            # OCR distorted: "CP1 37/19" → extract "CP137"
            r'([A-Z]{2})\s*(\d)[\s}]*(\d)\s*(\d)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 4:
                    # OCR distorted format: groups = (letter+letter, digit, digit, digit)
                    flight = match.group(1) + match.group(2) + match.group(3) + match.group(4)
                    return flight.upper().strip()
                else:
                    flight_str = match.group(1).upper()
                    return flight_str.split('/')[0] if '/' in flight_str else flight_str
        
        return None

    def _extract_flight_date(self, text: str) -> Optional[str]:
        """Extract flight date."""
        date_match = re.search(
            r'(?:date|departure|executed on)\s*[:=]?\s*'
            r'(\d{4}[-/\.]\d{2}[-/\.]\d{2}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})',
            text, re.IGNORECASE
        )
        if not date_match:
            date_match = re.search(r'(\d{1,2})[-/\.]([A-Z][a-z]{2})[-/\.](\d{2,4})', text, re.IGNORECASE)
        if date_match:
            try:
                groups = date_match.groups()
                if len(groups) == 3:
                    day, month_str, year_str = groups
                    month_map = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                                 'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
                    month = month_map.get(month_str.lower(), '01')
                    year = int(year_str)
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    return f"{year:04d}-{month}-{int(day):02d}"
                else:
                    groups_str = date_match.group(1)
                    parts = re.split(r'[-/\.]', groups_str)
                    if len(parts) == 3:
                        if len(parts[0]) == 4:
                            return f"{parts[0]}-{parts[1]}-{parts[2]}"
                        else:
                            return f"{parts[2]}-{parts[1]}-{parts[0]}"
            except (ValueError, IndexError):
                pass
        return None

    def _extract_goods_description(self, text: str) -> Optional[str]:
        """Extract goods description from cargo section. Multiple patterns."""
        patterns = [
            # Pattern 1: Common section headers
            r'(?:SAID TO CONTAIN|Consolidation|CONTENTS|GOODS|Nature of Goods|Nature and Quantity)[^\n]*\n+\s*([A-Za-z][A-Za-z0-9\s,\(\)-]*?)(?=\n\n|Chargeable|Prepaid|Total|RCP|€|$)',
            # Pattern 2: Direct keywords
            r'(?:Consolidation|CONSOLIDATED|LITHIUM|Electronics|Documents|Wireless|Router)\s+([A-Za-z0-9\s,\(\)-]+?)(?=\n|$)',
            # Pattern 3: After "as per" or description markers
            r'as\s+per\s+([A-Za-z][A-Za-z0-9\s,\(\)-]*?)(?=\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                goods_text = match.group(1).strip()
                goods_text = goods_text.split('\n')[0][:150].strip()
                # Filter out legal text
                if (goods_text and len(goods_text) > 3
                    and not re.search(r'SUBJECT|CONDITIONS|AGREED|CARRIED|SHIPPER', goods_text, re.IGNORECASE)):
                    return goods_text
        
        return None
        data = AwbData()
        confidences: List[AwbFieldConfidence] = []

        # AWB number
        m = AWB_PATTERN.search(text)
        if m:
            data.awb_prefix, data.awb_serial = m.group(1), m.group(2)
            confidences.append(AwbFieldConfidence(field="awb_number", value=f"{data.awb_prefix}-{data.awb_serial}", confidence=0.95))

        # Origin: "Airport of Departure" section (first priority)
        origin_match = re.search(r'Airport of Departure[^\n]*\n+\s*([A-Z]{3})', text, re.IGNORECASE)
        if origin_match:
            origin_code = origin_match.group(1).upper()
            if origin_code in COMMON_IATA:
                data.origin = origin_code
                confidences.append(AwbFieldConfidence(field="origin", value=data.origin, confidence=0.95))

        # Destination: "Airport of Destination" section or "HONG KONG" keyword
        dest_match = re.search(r'(?:Airport of Destination|To)[^\n]*\n+\s*([A-Z]{3}|HONG\s+KONG)', text, re.IGNORECASE)
        if dest_match:
            dest_str = dest_match.group(1).upper().replace(' ', '')
            if dest_str in COMMON_IATA:
                data.destination = dest_str
            elif 'HONGKONG' in dest_str:
                data.destination = 'HKG'
            
            if data.destination:
                confidences.append(AwbFieldConfidence(field="destination", value=data.destination, confidence=0.95))

        # Fallback: generic IATA search if sections not found
        if not data.origin or not data.destination:
            iata_matches = []
            for iata in sorted(COMMON_IATA, key=len, reverse=True):
                for m in re.finditer(r'\b' + iata + r'\b', text, re.IGNORECASE):
                    iata_matches.append((m.start(), iata.upper()))
            
            iata_matches.sort(key=lambda x: x[0])
            iata_codes = []
            seen = set()
            for _, code in iata_matches:
                if code not in seen:
                    iata_codes.append(code)
                    seen.add(code)
            
            if not data.origin and len(iata_codes) >= 1:
                data.origin = iata_codes[0]
                confidences.append(AwbFieldConfidence(field="origin", value=data.origin, confidence=0.7))
            if not data.destination and len(iata_codes) >= 2:
                data.destination = iata_codes[1]
                confidences.append(AwbFieldConfidence(field="destination", value=data.destination, confidence=0.7))
        
        # Pieces: more formats (1, 1 PCS, PCS: 1, etc.)
        pcs_match = re.search(r'(\d+)\s*(?:pcs|pieces?|pc\b)', text, re.IGNORECASE)
        if not pcs_match:
            pcs_match = re.search(r'(?:pcs|pieces?|pc\b)\s*[:=]?\s*(\d+)', text, re.IGNORECASE)
        if pcs_match:
            data.pieces = int(pcs_match.group(1))
            confidences.append(AwbFieldConfidence(field="pieces", value=str(data.pieces), confidence=0.85))
        
        # Weight: in manifest table "1 686.78K Q" or similar
        # Pattern 1: "686.78K Q" (number followed by K Q)
        wt_match = re.search(r'\s(\d+(?:\.\d+)?)\s*K\s*Q', text)
        if not wt_match:
            # Pattern 2: "686.78" followed by "kg" or similar
            wt_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|KG|KE|weight|wt)\b', text, re.IGNORECASE)
        if not wt_match:
            # Pattern 3: "weight: 686.78"
            wt_match = re.search(r'(?:weight|wt)\s*[:=]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if wt_match:
            wt_str = wt_match.group(1).replace(',', '.')
            data.weight = float(wt_str)
            confidences.append(AwbFieldConfidence(field="weight", value=str(data.weight), confidence=0.9))

        # Shipper: Estrai da sezione "Shipper's Name and Address", evita testo legale
        shipper_match = re.search(
            r'Shipper(?:\'?s)?\s*(?:Name and)?[^:]*?(?:Address|Account)?[^\n]*\n+'
            r'(?!lt is|It is|SUBJECT)' # Negative lookahead for legal text
            r'\s*([A-Z][A-Za-z0-9\s\.&,-]*?(?:S\.P\.A\.|Ltd|Inc|GmbH|SARL|SA|SRL))\b',
            text, re.IGNORECASE
        )
        if shipper_match:
            shipper_text = shipper_match.group(1).strip()
            # Split on MSC to get only first company
            if 'MSC' in shipper_text.upper():
                shipper_text = shipper_text.split('MSC')[0].strip()
            shipper_text = shipper_text.split('\n')[0].strip()
            data.shipper = shipper_text if shipper_text and len(shipper_text) > 2 and len(shipper_text) < 100 else None
            if data.shipper:
                confidences.append(AwbFieldConfidence(field="shipper", value=data.shipper, confidence=0.92))
        
        # Consignee: Estrai da sezione "Consignee's Name and Address", evita testo legale
        # Pattern: Cerca company name (con suffisso) dopo il label, prima di testo legale
        consignee_match = re.search(
            r'Consignee(?:\'?s)?\s*(?:Name and)?[^:]*?(?:Address)?[^\n]*\n+'
            r'(?:[^\n]*\n)*?' # Skip some lines that might be legal text
            r'(?!.*?SUBJECT|.*?CONDITIONS|.*?AGREED)'  # Don't match if followed by legal text
            r'([A-Z][A-Za-z0-9\s\.&,-]*?(?:Ltd|Inc|SRL|Corp|Co|Company|GmbH|S\.A|S\.p\.A|LLC)\b)',
            text, re.IGNORECASE | re.DOTALL
        )
        if consignee_match:
            consignee_text = consignee_match.group(1).strip()
            consignee_text = consignee_text.split('\n')[0][:80].strip()
            data.consignee = consignee_text if consignee_text and len(consignee_text) > 3 else None
            if data.consignee:
                confidences.append(AwbFieldConfidence(field="consignee", value=data.consignee, confidence=0.75))

        # Flight number: "OO158", "CP125", "AZ123", etc.
        flight_match = re.search(r'(?:flight|flt|handling)\s*(?:no\.?|number|#|code)?\s*[:=]?\s*([A-Z]{2}\d{1,4})', text, re.IGNORECASE)
        if not flight_match:
            flight_match = re.search(r'([A-Z]{2}\d{1,4})/\d{1,2}', text)
        if not flight_match:
            # Look in handling information section
            flight_match = re.search(r'Handling\s+Information[^\n]*\n?[^\n]*([A-Z]{2}\d{1,4})', text, re.IGNORECASE)
        if flight_match:
            flight_str = flight_match.group(1).upper()
            # Remove /day if present
            data.flight_no = flight_str.split('/')[0] if '/' in flight_str else flight_str
            confidences.append(AwbFieldConfidence(field="flight_number", value=data.flight_no, confidence=0.88))

        # Flight date: Cerca format DD-MMM-YY, DD/MM/YYYY, ecc
        date_match = re.search(
            r'(?:date|departure|executed on)\s*[:=]?\s*'
            r'(\d{4}[-/\.]\d{2}[-/\.]\d{2}|\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})',
            text, re.IGNORECASE
        )
        if not date_match:
            date_match = re.search(r'(\d{1,2})[-/\.]([A-Z][a-z]{2})[-/\.](\d{2,4})', text, re.IGNORECASE)
        if date_match:
            try:
                groups = date_match.groups()
                if len(groups) == 3:
                    day, month_str, year_str = groups
                    month_map = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                                 'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
                    month = month_map.get(month_str.lower(), '01')
                    year = int(year_str)
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    data.flight_date = f"{year:04d}-{month}-{int(day):02d}"
                    confidences.append(AwbFieldConfidence(field="flight_date", value=data.flight_date, confidence=0.75))
                else:
                    groups_str = date_match.group(1)
                    parts = re.split(r'[-/\.]', groups_str)
                    if len(parts) == 3:
                        if len(parts[0]) == 4:
                            data.flight_date = f"{parts[0]}-{parts[1]}-{parts[2]}"
                        else:
                            data.flight_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                        confidences.append(AwbFieldConfidence(field="flight_date", value=data.flight_date, confidence=0.75))
            except (ValueError, IndexError):
                pass

        # Agent: equals shipper (customer)
        if data.shipper:
            data.agent = data.shipper
            confidences.append(AwbFieldConfidence(field="agent", value=data.agent, confidence=0.92))

        # Goods description: Cerca "CONSOLIDATED", "LITHIUM", nature of goods, evita testo legale
        goods_match = re.search(
            r'(?:SAID TO CONTAIN|Consolidation|CONTENTS|GOODS|Nature of Goods|Nature and Quantity)\s*\n?'
            r'(?:.*?\n)*?' # Skip some lines
            r'([A-Za-z][A-Za-z0-9\s,()-]*?)' # Capture goods description
            r'(?=\n\n|Chargeable|Prepaid|Total|$)',
            text, re.IGNORECASE | re.DOTALL
        )
        # Alternative: look for goods in the manifest/cargo section
        if not goods_match:
            goods_match = re.search(
                r'(?:CONSOLIDATED|LITHIUM|Electronics|Documents)\s+([A-Za-z0-9\s,()-]+?)(?=\n|$)',
                text, re.IGNORECASE
            )
        if goods_match:
            goods_text = goods_match.group(1).strip()
            goods_text = goods_text.split('\n')[0][:100].strip()
            # Filter out if it's legal text
            if not re.search(r'SUBJECT|CONDITIONS|AGREED|CARRIED', goods_text, re.IGNORECASE):
                data.goods_description = goods_text if goods_text and len(goods_text) > 3 else None
                if data.goods_description:
                    confidences.append(AwbFieldConfidence(field="goods_description", value=data.goods_description, confidence=0.7))

        return AwbExtractionResult(data=data, confidences=confidences, raw_text=text)