"""
AWB Section Analyzer - Identifies logical sections of IATA AWB documents

The AWB document has a standardized structure:
- Box 1: Shipper information
- Box 2: Consignee information
- Box 3: Agent
- Cargo section: Piece count, weight, goods description
- Handling section: Flight number, date, etc.

This module analyzes OCR-extracted text to identify and extract these sections,
reducing ambiguity for LLM field extraction.
"""

import re
from typing import Dict, Optional, List, Tuple


class AwbSectionAnalyzer:
    """
    Analyzes OCR-extracted AWB text to identify document sections.
    
    Uses a combination of:
    - Header/label detection (e.g., "BOX 1", "SHIPPER", "CONSIGNEE")
    - Layout patterns typical of IATA AWB forms
    - Content heuristics
    """

    # Section header patterns - what marks the start of each section
    SECTION_PATTERNS = {
        'shipper': [
            r'(?:BOX\s*1|SHIPPER|SENDER|FROM|EXPÉDITOR)',
            r'(?:CONTA\s*1|MITTENTE)'  # Italian
        ],
        'consignee': [
            r'(?:BOX\s*2|CONSIGNEE|RECEIVER|TO|DESTINATION PARTY|DESTINATAIRE)',
            r'(?:CONTA\s*2|DESTINATARIO)'  # Italian
        ],
        'agent': [
            r'(?:BOX\s*3|AGENT|FREIGHT FORWARDER|CUSTOMS BROKER)',
            r'(?:CONTA\s*3|AGENTE)'  # Italian
        ],
        'accounting_info': [
            r'(?:BOX\s*4|ACCOUNTING|INVOICE|BILLING)',
            r'(?:CONTA\s*4)'  # Italian
        ],
        'cargo': [
            r'(?:CARGO|GOODS|PIECE|WEIGHT|GROSS WEIGHT|KG|GWT|CONTENTS)',
            r'(?:CARICO|MERCI|PESO)'  # Italian
        ],
        'handling': [
            r'(?:HANDLING|FLIGHT|DATE|DEPARTURE|FLIGHT NO|ACCOUNT NUMBER)',
            r'(?:GESTIONE|VOLO|DATA)'  # Italian
        ],
    }

    # Minimum text length for a section to be considered valid
    MIN_SECTION_LENGTH = 10

    def analyze(self, text: str) -> Dict[str, str]:
        """
        Analyze OCR text and extract logical sections.
        
        Args:
            text: Raw OCR-extracted text from AWB document
            
        Returns:
            Dictionary mapping section names to extracted text blocks:
            {
                'shipper': '...',
                'consignee': '...',
                'agent': '...',
                'accounting_info': '...',
                'cargo': '...',
                'handling': '...'
            }
        """
        sections = {}
        
        # Find all section boundaries
        boundaries = self._find_section_boundaries(text)
        
        # Extract text for each section
        for section_name in self.SECTION_PATTERNS.keys():
            section_text = self._extract_section(text, section_name, boundaries)
            if section_text:
                sections[section_name] = section_text
        
        # Add full text as fallback
        sections['full_text'] = text
        
        return sections

    def _find_section_boundaries(self, text: str) -> Dict[str, List[Tuple[int, int]]]:
        """
        Find all occurrences of section headers in the text.
        
        Returns:
            Dict mapping section names to list of (start_pos, end_pos) tuples
        """
        boundaries = {}
        
        for section_name, patterns in self.SECTION_PATTERNS.items():
            positions = []
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                    positions.append((match.start(), match.end()))
            
            # Remove duplicates and sort
            positions = sorted(set(positions))
            if positions:
                boundaries[section_name] = positions
        
        return boundaries

    def _extract_section(
        self, 
        text: str, 
        section_name: str, 
        boundaries: Dict[str, List[Tuple[int, int]]]
    ) -> Optional[str]:
        """
        Extract text for a specific section between its header and the next section.
        
        Args:
            text: Full OCR text
            section_name: Name of section to extract
            boundaries: All section boundaries found
            
        Returns:
            Extracted section text or None if not found
        """
        if section_name not in boundaries or not boundaries[section_name]:
            return None
        
        # Get the start position of this section
        section_start = boundaries[section_name][0][1]  # After the header
        
        # Find the next section after this one
        section_end = len(text)
        for other_section, other_positions in boundaries.items():
            if other_section == section_name:
                continue
            for pos_start, pos_end in other_positions:
                if pos_start > section_start and pos_start < section_end:
                    section_end = pos_start
        
        # Extract and clean section text
        section_text = text[section_start:section_end].strip()
        
        # Remove common noise patterns (boxes, lines, etc.)
        section_text = self._clean_section_text(section_text)
        
        if len(section_text) >= self.MIN_SECTION_LENGTH:
            return section_text
        
        return None

    def _clean_section_text(self, text: str) -> str:
        """
        Clean section text by removing common OCR artifacts and noise.
        
        Args:
            text: Raw section text
            
        Returns:
            Cleaned text
        """
        # Remove excessive whitespace
        text = re.sub(r'\n\s*\n', '\n', text)
        text = re.sub(r' +', ' ', text)
        
        # Remove box drawing characters
        text = re.sub(r'[┌┐└┘─│├┤┬┴┼═║]', '', text)
        text = re.sub(r'[╔╗╚╝═║]', '', text)
        
        # Remove repeated dashes or underscores (typically used as separators)
        text = re.sub(r'(-{3,}|_{3,})', '', text)
        
        return text.strip()

    def analyze_with_confidence(self, text: str) -> Dict[str, Dict[str, any]]:
        """
        Analyze sections with confidence scores.
        
        Returns sections with metadata:
        {
            'section_name': {
                'text': '...',
                'confidence': 0.95,  # How sure we are this is the right section
                'headers_found': [...]  # Which patterns matched
            }
        }
        """
        boundaries = self._find_section_boundaries(text)
        results = {}
        
        for section_name, positions in boundaries.items():
            section_text = self._extract_section(text, section_name, boundaries)
            
            if section_text:
                # Confidence based on how many headers matched and text length
                num_headers = len(positions)
                text_length_confidence = min(1.0, len(section_text) / 200)  # Normalize to max 200 chars
                confidence = min(1.0, (num_headers * 0.7 + text_length_confidence * 0.3))
                
                results[section_name] = {
                    'text': section_text,
                    'confidence': confidence,
                    'headers_found': len(positions),
                    'length': len(section_text)
                }
        
        return results

    def debug_sections(self, text: str) -> str:
        """
        Generate a debug report showing identified sections.
        Useful for troubleshooting OCR or section detection issues.
        """
        results = self.analyze_with_confidence(text)
        
        report = "AWB SECTION ANALYSIS REPORT\n"
        report += "=" * 60 + "\n\n"
        
        for section_name, data in results.items():
            report += f"[{section_name.upper()}]\n"
            report += f"  Confidence: {data['confidence']:.2%}\n"
            report += f"  Headers found: {data['headers_found']}\n"
            report += f"  Length: {data['length']} chars\n"
            report += f"  Text preview: {data['text'][:100]}...\n\n"
        
        return report
