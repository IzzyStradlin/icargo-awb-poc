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

        # Chargeable weight — labeled extraction (more reliable than generic weight)
        chargeable_val = self._extract_chargeable_weight(text)
        if chargeable_val:
            data.chargeable_weight = chargeable_val
            confidences.append(AwbFieldConfidence(field="chargeable_weight", value=str(data.chargeable_weight), confidence=0.85))

        # Rate per kg
        rate_val = self._extract_rate(text)
        if rate_val:
            data.rate = rate_val
            confidences.append(AwbFieldConfidence(field="rate", value=str(data.rate), confidence=0.80))

        # Total charge — from RCP data row
        total_charge_val = self._extract_total_charge(text)
        if total_charge_val:
            data.total_charge = total_charge_val
            confidences.append(AwbFieldConfidence(field="total_charge", value=str(data.total_charge), confidence=0.85))

        # Goods description - from cargo section
        cargo_section = (sections or {}).get('cargo', '')
        goods_val = self._extract_goods_description(cargo_section or text)
        if goods_val:
            data.goods_description = goods_val
            confidences.append(AwbFieldConfidence(field="goods_description", value=data.goods_description, confidence=0.7))

        return AwbExtractionResult(data=data, confidences=confidences, raw_text=text)


    def extract_all(
        self, 
        texts: List[str], 
        sections_list: Optional[List[Dict[str, str]]] = None
    ) -> List[AwbExtractionResult]:
        """
        Extract AWB fields from multiple text blocks (e.g., multiple AWBs per PDF).
        
        Args:
            texts: List of text strings (one per AWB document)
            sections_list: Optional list of section dicts (parallel to texts)
        
        Returns:
            List of AwbExtractionResult, one per input text
        """
        results = []
        sections_list = sections_list or [None] * len(texts)
        
        for text, sections in zip(texts, sections_list):
            result = self.extract(text, sections)
            results.append(result)
        
        return results

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
                # Case-SENSITIVE: avoids matching Italian words like "per", "sin", "fra", "mar"
                for m in re.finditer(r'\b' + iata + r'\b', text):
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
        """Extract pieces from text. Handle various OCR formats and AWB standard locations."""
        # Try multiple patterns for pieces - AWB standard provides specific locations
        patterns = [
            # Pattern 1: "No. of Pieces RCP" label (most reliable — the actual column header)
            r'No\.\s*(?:of\s+)?Pieces?\s*RCP\s*[:\|/}]?\s*(\d+)',
            # Pattern 2: After generic "No. of Pieces" label
            r'No\.\s*(?:of\s+)?Pieces?\s*[:\|/}]?\s*(\d+)',
            # Pattern 3: "Pieces:" or "PCS:" directly — but NOT if followed by "ON" (goods description)
            r'(?:Number\s+of\s+)?Pieces?[:\|/}]?\s*(\d+)',
            r'PCS[:\|/}]?\s*(\d+)',
            # Pattern 4: Number followed by "pc/pcs" — exclude "NNN PCS ON <pallet>" pattern
            r'(\d+)\s*[|/}]?\s*(?:pc|pcs|pieces)\b(?!\s*ON\b)',
            # Pattern 5: In manifest/handling section (less reliable)
            r'(\d+)\s*(?:pieces?|pcs)\s*(?:of|at)',
            # Pattern 6: Standalone number before "x" (e.g., "2 x 12kg")
            r'^(\d+)\s*x\s*\d+',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    pieces = int(match.group(1))
                    if 0 < pieces < 10000:  # Reasonable range: 1 to 9999
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

    def _extract_chargeable_weight(self, text: str) -> Optional[float]:
        """Extract chargeable weight — distinct from gross weight and total charge.

        Primary strategy: parse the AWB table data row (RCP section), which has a
        fixed column order:  pieces | gross_wt/K | chargeable_wt | rate | total_charge
        Example row:  "1 806.91/K] ik 2750.0 4.50) 12375.00}"

        Fallback: look for "Chargeable Weight" label (when label is on a clean line).
        """
        # --- Strategy 1: RCP data-row parsing (handles split column headers) ---
        # The row appears right after the "RCP Item No." header line.
        # Structure: <pieces> <gross>/K<noise> <chargeable> <rate>) <total>}
        rcp_match = re.search(
            r'RCP\s*Item\s*No\.?\s*\n\s*'      # "RCP Item No." line
            r'(\d+)\s+'                          # group(1): pieces
            r'(\d+[.,]\d+)\s*/\s*[Kk][^\d\n]*'  # group(2): gross_weight/K  + noise
            r'(\d+[.,]\d+)\s+'                   # group(3): chargeable_weight  ← what we want
            r'(\d+[.,]\d+)\s*\)\s*'              # group(4): rate
            r'(\d+[.,]\d+)',                      # group(5): total_charge
            text,
        )
        if rcp_match:
            try:
                return float(rcp_match.group(3).replace(',', '.'))
            except ValueError:
                pass

        # --- Strategy 2: label-based (clean PDFs / other AWB forms) ---
        label_patterns = [
            # Label and value on same line: "Chargeable Weight  2750"
            r'[Cc]hargeable\s+[Ww](?:eight|t)\b[^\d\n]{0,40}(\d+(?:[.,]\d+)?)',
            # Label then value on next line
            r'[Cc]hargeable\s+[Ww](?:eight|t)\b[^\n]*\n\s*(\d+(?:[.,]\d+)?)',
            # Abbreviated: "Chg Wt" or "ChgWt"
            r'[Cc]hg\.?\s*[Ww]t\.?[^\d\n]{0,20}(\d+(?:[.,]\d+)?)',
        ]
        candidates = []
        for pattern in label_patterns:
            for m in re.finditer(pattern, text):
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if val > 0:
                        candidates.append(val)
                except ValueError:
                    continue
        if not candidates:
            return None
        # Prefer smallest candidate (chargeable weight ≤ total charge by definition)
        candidates.sort()
        return candidates[0]

    def _extract_total_charge(self, text: str) -> Optional[float]:
        """Extract total charge from the AWB cargo table.

        Primary: parse the RCP data row (last number on the row, ends with '}').
        Fallback: look for repeating total-line (e.g. "806.91  12375.00}").
        """
        # Strategy 1: RCP data-row — total_charge is group(5)
        rcp_match = re.search(
            r'RCP\s*Item\s*No\.?\s*\n\s*'
            r'\d+\s+'
            r'\d+[.,]\d+\s*/\s*[Kk][^\d\n]*'
            r'\d+[.,]\d+\s+'
            r'\d+[.,]\d+\s*\)\s*'
            r'(\d+[.,]\d+)',                  # group(1): total_charge
            text,
        )
        if rcp_match:
            try:
                return float(rcp_match.group(1).replace(',', '.'))
            except ValueError:
                pass

        # Strategy 2: subtotal line "806.91  12375.00}" (gross_weight + total on same line)
        subtotal_match = re.search(
            r'\d+[.,]\d+\s+(\d{4,}[.,]\d+)\s*\}',
            text,
        )
        if subtotal_match:
            try:
                return float(subtotal_match.group(1).replace(',', '.'))
            except ValueError:
                pass

        return None

    def _extract_rate(self, text: str) -> Optional[float]:
        """Extract rate/charge per kg from the Rate column."""
        patterns = [
            # "Rate/Charge" label then value
            r'[Rr]ate\s*/\s*[Cc]harge[^\d\n]{0,20}(\d+(?:[.,]\d+)?)',
            # "Rate" label with value < 1000 (avoid matching AWB numbers)
            r'\b[Rr]ate\b[^\d\n]{0,20}(\d+(?:[.,]\d+)?)',
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 0 < val < 1000:  # Rates per kg are always < 1000
                        return val
                except ValueError:
                    continue
        return None

    def _extract_shipper(self, text: str) -> Optional[str]:
        """Extract shipper name from text.

        After the column-split fix in OCR, each column is on its own line, so
        "CEVA AIR&OCEAN" and "CEVA HONG KONG" are no longer merged.

        Strategy:
        1. Find the 'Shipper' label line.
        2. Collect the next 1-3 non-address, non-boilerplate lines as the name.
        3. Stop when a legal suffix is found (S.P.A., Ltd, …).
        4. If no label found: return None (LLM fallback will be used).
        """
        CARRIER_KEYWORDS = {
            'MSC AIR', 'ALISCARGO', 'LUFTHANSA', 'AIR FRANCE', 'KLM',
            'BRITISH AIRWAYS', 'UNITED AIRLINES', 'DELTA', 'CATHAY PACIFIC',
            'EMIRATES', 'CARGOLUX', 'KOREAN AIR', 'SINGAPORE AIRLINES',
            'JAPAN AIRLINES', 'QANTAS', 'IBERIA', 'SWISS', 'TURKISH AIRLINES',
            'ETIHAD',
        }

        # Match "Shipper" label — allow optional apostrophe+s, optional "Name and Address"
        m = re.search(
            r'(?:^|[\n])[ \t]*Shipper[\'s]*[ \t]*(?:Name[ \t]+and[ \t]+Address)?[^\n]*\n',
            text, re.IGNORECASE
        )
        if not m:
            return None

        after = text[m.end():]
        raw_lines = after.split('\n')

        # Lines to skip: street/postal/boilerplate
        _SKIP = re.compile(
            r'^(?:VIA |STRADA |CORSO |PIAZZA |P\.?O\.?\s*BOX|TEL|FAX|'
            r'SUBJECT|CONDITIONS|AGREED|ISSUED\s+BY|AIR\s+WAYBILL|NOT\s+NEGOTIABLE|'
            r'AIRPORT|HANDLING|FIRST\s+CARRIER|\d{4,})',
            re.IGNORECASE
        )

        name_lines: List[str] = []
        for line in raw_lines[:8]:
            line = line.strip()
            if not line:
                if name_lines:
                    break   # blank line ends the name block
                continue
            if _SKIP.match(line):
                break
            # Stop if this line is clearly a consignee label (column-split artefact guard)
            if re.match(r'Consignee', line, re.IGNORECASE):
                break
            name_lines.append(line)
            # Stop after a line that ends with a legal suffix
            if re.search(
                r'\b(?:S\.P\.A\.?|S\.R\.L\.?|Ltd\.?|Inc\.?|GmbH|LLC|SRL|SPA|Corp)\b',
                line, re.IGNORECASE
            ):
                break

        if not name_lines:
            return None

        shipper_text = ' '.join(name_lines).strip()
        shipper_upper = shipper_text.upper()

        for carrier in CARRIER_KEYWORDS:
            if carrier in shipper_upper:
                return None

        if (shipper_upper in {'MALPENSA', 'MILANO', 'ROMA', 'LONDON', 'PARIS', 'HONG KONG'}
                or len(shipper_text) < 4 or len(shipper_text) > 120
                or re.search(r'SUBJECT|CONDITIONS|SHIPMENT MAY|AGREED', shipper_text, re.IGNORECASE)):
            return None

        return shipper_text

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
        """Extract flight number from AWB. Handle OCR distortion and various locations."""
        # AWB standard: Flight appears in "Requested Flight/Date" section
        # Format: AIRLINE_CODE + FLIGHT_NUMBER (e.g., CP137, AZ456, BA123)

        patterns = [
            # Pattern 0 (HIGHEST PRIORITY): Spatially-reconstructed routing annotation.
            # pdf_text_extractor appends "ROUTING: {TO} {CARRIER} {FLIGHT}/{DATE} ..."
            # for native PDFs, bypassing the column-linearisation garbling.
            # Example: "ROUTING: HKG CP 113/19 EUR PPX NVD NCV"
            #          → carrier=CP, flight=113 → "CP113"
            r'ROUTING:\s+[A-Z]{2,3}\s+([A-Z]{2})\s+(\d{2,5})(?:/\d{1,2})?',

            # Pattern 1: "Requested Flight/Date" label — most reliable IATA AWB location
            r'Requested\s+Fl(?:ight|t)\.?\s*[/\\]?\s*Date[^\n]*\n?\s*([A-Z]{2}\s*\d{1,5})',

            # Pattern 2: "Flight/Date" or "Flight:" label
            r'(?:Flt|Flight)[./\s]*Date[^\n]*[:=]?\s*([A-Z]{2}\s*\d{1,5})',
            r'(?:Flt|Flight)[^\n]*[:=]?\s*([A-Z]{2}\s*\d{1,5})',

            # Pattern 3: Code with slash date suffix (e.g., "CP137/16" or "CP0137/19")
            r'([A-Z]{2}\s*\d{1,5})\s*/\s*\d{1,2}(?:\s|$)',

            # Pattern 4: In "Handling Information" section
            r'Handling\s+Information[^\n]*(?:\n[^\n]*){0,5}?([A-Z]{2}\d{1,5})',

            # Pattern 5: Fallback generic — 2-letter code + 2-5 digits, preceded by whitespace/newline
            r'(?:^|\s|[\n:\|])([A-Z]{2}\d{2,5})(?:\s|[\n:/]|$)',

            # Pattern 6: OCR distorted with spaces between characters (e.g., "C P 1 3 7")
            r'([A-Z])\s+([A-Z])\s+(\d)\s+(\d)\s+(\d)',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    groups = match.groups()

                    # Pattern 0: two groups → carrier code + flight number
                    if len(groups) == 2 and groups[1] is not None:
                        flight_str = (groups[0].replace(' ', '') + groups[1].replace(' ', '')).upper()
                        if re.match(r'^[A-Z]{2}\d{2,5}$', flight_str):
                            return flight_str

                    # Pattern 6: reassemble spaced characters
                    if len(groups) == 5 and all(g is not None for g in groups):
                        flight = ''.join(g.upper() for g in groups)
                        if re.match(r'^[A-Z]{2}\d{3}$', flight):
                            return flight

                    # Standard patterns: flight is first group — strip internal spaces
                    flight_str = groups[0].replace(' ', '').upper()
                    if re.match(r'^[A-Z]{2}\d{2,5}$', flight_str):
                        return flight_str

                except (ValueError, IndexError, AttributeError):
                    continue

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

        # Shipper: Extract from "Shipper's Name and Address" section, avoid legal text
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
        
        # Consignee: Extract from "Consignee's Name and Address" section, avoid legal text
        # Pattern: Look for company name (with suffix) after the label, before legal text
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

        # Goods description: Look for "CONSOLIDATED", "LITHIUM", nature of goods, avoid legal text
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