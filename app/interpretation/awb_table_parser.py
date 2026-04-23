"""
AWB Quantity/Weight Table Parser - Handles messy OCR-extracted tables

The physical AWB has a table with:
- No. of Pieces
- Gross Weight  
- Chargeable Weight

OCR mangles this table badly, but we can still extract the numbers
by looking for patterns.
"""

import re
from typing import Optional, Dict, Tuple


class AwbTableParser:
    """Parse messy OCR-extracted tables from AWB documents"""
    
    @staticmethod
    def extract_quantity_and_weights(text: str) -> Dict[str, Optional[float]]:
        """
        Extract pieces, gross_weight, chargeable_weight from messy table.
        
        Returns dict with keys:
        - pieces: number of pieces (int/float)
        - gross_weight: weight in kg (float)
        - chargeable_weight: billing weight in kg (float)
        """
        result = {
            'pieces': None,
            'gross_weight': None,
            'chargeable_weight': None,
        }
        
        # Find the table section - look for lines with numbers and keywords
        # Patterns like "239 PCS", "12375.00", "2750"
        
        # 1. Extract pieces - often appears as "XXX PCS" or similar
        pieces_patterns = [
            r'\b(\d{2,5})\s+PCS\b',  # 239 PCS (2+ digits to avoid "1 PCS")
            r'\b(\d{2,5})\s+(?:Pieces|PIECES)\b',  # 239 Pieces (2+ digits)
            r'(?:Pieces|No\.\s+Of).*?(\d{2,5})\b',  # No. Of Pieces: 239 (2+ digits)
        ]
        
        for pattern in pieces_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Take the largest match (usually the correct quantity, not item numbers)
                try:
                    result['pieces'] = max(int(m) for m in matches)
                    break
                except (ValueError, IndexError):
                    continue
        
        # 2. Extract gross weight - usually a decimal number near "Gross Weight" label
        # In the table it appears as something like "12375.00"
        gross_weight_patterns = [
            # Look for pattern: Gross ... Weight followed by number
            r'Gross\s+[\w\s]*?Weight\s*[\w\s]*?(\d+[.,]\d+|\d+)\b',
            # Look for large numbers (typically weights are 4+ digits like 12375)
            r'\b(\d{4,5}[.,]\d{1,2})\b',
            # In messy table: number like 12375.00
            r'\}\s*\|?(\d{4,5}[.,]\d+)',
        ]
        
        for pattern in gross_weight_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    weight_str = match.group(1).replace(',', '.')
                    weight = float(weight_str)
                    # Sanity check: weights should be > 50kg typically
                    if weight > 50:
                        result['gross_weight'] = weight
                        break
                except (ValueError, IndexError, AttributeError):
                    continue
        
        # 3. Extract chargeable weight
        # Usually smaller than gross weight, in range 1000-5000 typically
        # Exclude tariff rates like 806.91/K (rate per kg) and agent codes like 7889
        all_numbers = re.findall(r'\b(\d+[.,]\d+|\d+)\b', text)
        
        chargeable_candidates = []
        for num_str in all_numbers:
            try:
                num = float(num_str.replace(',', '.'))
                
                # Exclude very small numbers (< 100) - likely rates/percentages
                if num < 100:
                    continue
                
                # Exclude agent codes: typically 3-5 digits like 7889/0015 or 38-4
                # Check if surrounded by slashes or dashes
                idx = text.find(num_str)
                if idx >= 0:
                    context = text[max(0, idx-15):idx+len(num_str)+15]
                    
                    # Skip if it looks like an agent code: "XXX-YYYY" or "XXXX/YYYY"
                    if re.search(r'\d+[/-]\d+', context):
                        continue
                    
                    # Skip if it looks like a rate: "XXX.XX/K" or "X.XX"
                    if '/K' in context or '/KG' in context:
                        continue
                
                # Chargeable weight sanity checks
                if result['gross_weight']:
                    if 100 < num < result['gross_weight']:
                        chargeable_candidates.append(num)
                else:
                    if 100 < num < 10000:
                        chargeable_candidates.append(num)
            except (ValueError, TypeError):
                continue
        
        # Pick the largest candidate (typically chargeable weight)
        if chargeable_candidates:
            result['chargeable_weight'] = max(chargeable_candidates)
        
        return result
    
    @staticmethod
    def extract_flight_info(text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract flight number and date from messy text.
        
        Returns: (flight_number, flight_date)
        """
        flight_number = None
        flight_date = None
        
        # Flight number patterns: CP113/19, BA285, LH 2054, IN233, etc.
        flight_patterns = [
            r'\b([A-Z]{2,3}\d{1,4}/\d{1,2})\b',  # CP113/19
            r'\b([A-Z]{2,3}\s*\d{1,4})\b',  # BA 285 or BA285
        ]
        
        for pattern in flight_patterns:
            match = re.search(pattern, text)
            if match:
                flight_number = match.group(1).replace(' ', '')
                break
        
        # Date patterns: various formats
        date_patterns = [
            r'\b(\d{2}-\d{2}-\d{4})\b',  # 01-02-2023
            r'\b(\d{4}-\d{2}-\d{2})\b',  # 2023-01-02
            r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b',  # 01/02/2023
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                flight_date = match.group(1)
                break
        
        return flight_number, flight_date


def test_table_parser():
    """Test the table parser with real messy OCR"""
    
    messy_ocr = r"""
    Gross ¥@] [Rate Class Chargeable
    No. Of |. Weight » Weight Total 'Nature and Quantity of Goods
    Pieces Commodity 'Charge otal (incl, Dimensions or Volume)
    RCP. tem No.
    1 806.91/K 4.50) 12375.00} |Consolidation as per attached list
    239 PCS ON PMC10434CP Charge: 2750.00
    VOL 16.500 M3
    239 SLAC
    1 806.91 12375.00}
    
    Flight: CP113/19
    """
    
    parser = AwbTableParser()
    
    # Test quantity/weight extraction
    result = parser.extract_quantity_and_weights(messy_ocr)
    print("Table Parser Results:")
    print(f"  Pieces: {result['pieces']} (expected: 239)")
    print(f"  Gross Weight: {result['gross_weight']} (expected: 12375.0)")
    print(f"  Chargeable Weight: {result['chargeable_weight']} (expected: 2750.0)")
    
    # Test flight extraction
    flight, date = parser.extract_flight_info(messy_ocr)
    print(f"\nFlight Info:")
    print(f"  Flight: {flight} (expected: CP113/19)")
    print(f"  Date: {date}")


if __name__ == '__main__':
    test_table_parser()
