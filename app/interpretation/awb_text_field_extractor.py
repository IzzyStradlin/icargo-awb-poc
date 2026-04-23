"""
AWB Text Field Extractor - Handles messy OCR with T&C text mixed in

Strategies:
1. Identify and exclude T&C sections (marked by legal language)
2. Extract company names intelligently (skip generic terms)
3. Extract addresses separately
4. Handle corrupted/mixed text gracefully
"""

import re
from typing import Optional, Dict, Tuple


class AwbTextFieldExtractor:
    """Extract text fields from messy AWB OCR while avoiding T&C text"""
    
    # Legal/T&C keywords that indicate we're in boilerplate text
    TERMS_CONDITIONS_KEYWORDS = [
        r"It is agreed that",
        r"SUBJECT TO THE CONDITIONS",
        r"SUBJECT TO THE",
        r"CARRIER DEEMS",
        r"CARRIER'S LIMITATION",
        r"limitation of liability",
        r"SHIPPER AGREES",
        r"SHIPPER'S ATTENTION",
        r"CONDITIONS OF CONTRACT",
        r"may be carried by any",
        r"INTERMEDIATE STOPPING",
        r"UNLESS SPECIFIC CONTRARY",
        r"GOODS MAY BE CARRIED",
    ]
    
    # Company suffixes to help identify company names
    COMPANY_SUFFIXES = [
        r'\bLIMITED\b',
        r'\bLTD\b',
        r'\bLLC\b',
        r'\bINC\b',
        r'\bCO\b',
        r'\bCO[.,]\s?LTD\b',
        r'\bS\.P\.A\b',
        r'\bGmbH\b',
        r'\bAG\b',
        r'\bSA\b',
        r'\bSARL\b',
        r'\bSRO\b',
    ]
    
    @staticmethod
    def is_terms_conditions_text(text: str) -> bool:
        """Check if text contains T&C markers"""
        text_upper = text.upper()
        for keyword in AwbTextFieldExtractor.TERMS_CONDITIONS_KEYWORDS:
            if re.search(keyword, text, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def clean_text_field(text: str) -> str:
        """
        Clean a text field by:
        1. Removing extra whitespace
        2. Removing line breaks in middle of addresses
        3. Removing OCR artifacts
        """
        # Remove multiple spaces
        text = re.sub(r' +', ' ', text)
        
        # Remove OCR artifacts (common corruptions)
        text = re.sub(r'[┌┐└┘─│├┤┬┴┼═║╔╗╚╝]', '', text)
        text = re.sub(r'[¥@\[\]\¬]', '', text)
        
        # Remove repeated dashes/underscores
        text = re.sub(r'(-{3,}|_{3,})', '', text)
        
        # Clean up common OCR errors
        replacements = {
            r"'(?=\w)": "",  # Remove leading apostrophes before letters
            r"'\s*([A-Z])": r"\1",  # Remove apostrophe before capitals
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text)
        
        return text.strip()
    
    @staticmethod
    def extract_shipper(text: str) -> Optional[str]:
        """
        Extract shipper name - the first company line after "Shipper's Name and Address" label
        """
        # Find shipper label
        match = re.search(r"Shipper[\s']*s\s+Name\s+and\s+Address(.*)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        
        # Get everything after the label
        after_label = match.group(1)
        
        # Split into lines and find first valid company name
        lines = after_label.split('\n')
        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue
            # Skip labels and generic text
            if any(keyword in line for keyword in ["Account", "Negotiable", "Consignee", "Copies", "validity", "Air Waybill", "issued by"]):
                continue
            # Return first substantial line
            if len(line) > 5:
                cleaned = AwbTextFieldExtractor.clean_text_field(line)
                # Remove trailing "Air Waybill" if it got included
                cleaned = re.sub(r'\s+Air Waybill.*$', '', cleaned, flags=re.IGNORECASE)
                return cleaned if cleaned else None
        
        return None
    
    @staticmethod
    def extract_consignee(text: str) -> Optional[str]:
        """
        Extract consignee name - skip T&C text, find first company name
        """
        # Find consignee label
        match = re.search(r"Consignee[\s']*s?\s+[Nn]ame\s+and\s+Address[:\s]+(.*)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        
        # Get everything after the label
        after_label = match.group(1)
        
        # Split into lines and process
        lines = after_label.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue
            
            # Skip account number line and labels
            if any(keyword in line for keyword in ["Account", "Itis agreed", "SUBJECT", "CONDITIONS"]):
                continue
            
            # Skip obvious T&C text
            if AwbTextFieldExtractor.is_terms_conditions_text(line):
                continue
            
            # Skip pure address/number lines
            if re.match(r'^\d+', line):  # Starts with number (address)
                continue
            
            # Found a good line - return it
            if len(line) > 5:
                return AwbTextFieldExtractor.clean_text_field(line)
        
        return None
    
    @staticmethod
    def extract_agent(text: str) -> Optional[str]:
        """
        Extract issuing carrier's agent name.
        Handle OCR errors in label.
        """
        # Try to find the agent section with various patterns
        patterns = [
            r"[Ii]ssuing Carriers? Agent Name and City(.*?)(?:[Aa]gent[\s']*s?\s+IATA|'Accounting)",
            r"Tssuing.*?Agent.*?Name.*?City(.*?)(?:IATA|Code|'Agent)",  # OCR error: Tssuing
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section = match.group(1)
                
                # Get first few non-empty lines
                lines = section.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 5:
                        continue
                    # Skip phone/contact info
                    if re.match(r'^[\d+\s()-]+$', line):
                        continue
                    if 'TE' in line and len(line) < 20:
                        continue
                    # Return first substantial line
                    return AwbTextFieldExtractor.clean_text_field(line)
        
        return None
    
    @staticmethod
    def extract_destination(text: str) -> Optional[str]:
        """
        Extract destination airport code from Routing section.
        Handle OCR errors in label name.
        """
        # Look for "[to XXX" pattern first (most reliable)
        match = re.search(r'\[?\s*to\s+([A-Z]{3})', text, re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            if len(code) == 3 and code.isalpha():
                return code
        
        # Try to find in Routing/Destination section
        routing_match = re.search(
            r"Routing and Des[t]?i?n?ation(.*?)(?:Declared|Insurance|Handling|[Rr]ate)",
            text,
            re.IGNORECASE | re.DOTALL
        )
        
        if routing_match:
            section = routing_match.group(1)
            # Look for 3-letter airport codes in this section
            codes = re.findall(r'\b([A-Z]{3})\b', section)
            
            # Filter out common English words
            exclude_words = {'THE', 'AND', 'FOR', 'NOT', 'ALL', 'ANY', 'MAY', 'ONE', 'TWO', 'HAS', 'ARE'}
            for code in codes:
                if code not in exclude_words:
                    return code
        
        return None


def test_text_extractor():
    """Test text field extraction with real OCR"""
    from test_real_ocr import REAL_OCR
    
    extractor = AwbTextFieldExtractor()
    
    print("=" * 80)
    print("TEXT FIELD EXTRACTION TEST")
    print("=" * 80)
    
    shipper = extractor.extract_shipper(REAL_OCR)
    print(f"\nShipper: {shipper}")
    
    consignee = extractor.extract_consignee(REAL_OCR)
    print(f"Consignee: {consignee}")
    
    agent = extractor.extract_agent(REAL_OCR)
    print(f"Agent: {agent}")
    
    destination = extractor.extract_destination(REAL_OCR)
    print(f"Destination: {destination}")


if __name__ == '__main__':
    test_text_extractor()
