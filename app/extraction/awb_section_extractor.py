# app/extraction/awb_section_extractor.py
"""
Extracts AWB document sections based on physical layout (Y-coordinates).
Standardized AWB format has consistent section positions.
"""

from typing import Dict, List, Tuple, Optional
import fitz  # pymupdf


class TextBlock:
    """Represents a text block with coordinates."""
    def __init__(self, text: str, y0: float, y1: float, x0: float, x1: float, size: float = 0):
        self.text = text.strip()
        self.y0 = y0
        self.y1 = y1
        self.x0 = x0
        self.x1 = x1
        self.size = size

    def __repr__(self):
        return f"TextBlock(y={self.y0:.0f}-{self.y1:.0f}, text={self.text[:30]}...)"


class AwbSectionExtractor:
    """
    Extracts AWB sections based on document structure and Y-coordinates.
    Standard AWB format has consistent section layout.
    """
    
    # Known AWB section headers (case-insensitive)
    SECTION_HEADERS = {
        'shipper': ['shipper', 'from', 'sender'],
        'consignee': ['consignee', 'to', 'receiver', 'consignees'],
        'agent': ['agent', 'handling agent', 'airline'],
        'handling': ['handling', 'handling information'],
        'cargo': ['cargo', 'commodities', 'consolidation', 'said to contain', 'contents'],
        'charges': ['charges', 'freight charges'],
        'customs': ['customs', 'remarks'],
    }

    def __init__(self):
        pass

    def extract_sections(self, raw_pdf: bytes, max_pages: Optional[int] = None) -> Dict[str, str]:
        """
        Extract AWB sections from PDF based on layout.
        
        Returns:
            Dict with keys: shipper, consignee, agent, handling, cargo, customs, full_text
            Each value is the text content of that section
        """
        try:
            import fitz
        except Exception:
            raise RuntimeError("PyMuPDF not installed. Run: pip install pymupdf")

        doc = fitz.open(stream=raw_pdf, filetype="pdf")
        total_pages = doc.page_count
        max_pages = max_pages or total_pages
        max_pages = min(max_pages, total_pages)

        all_blocks: List[TextBlock] = []
        full_text_parts = []

        # Extract all text blocks with coordinates
        for page_idx in range(max_pages):
            page = doc.load_page(page_idx)
            text_dict = page.get_text("dict")  # Returns structure with coordinates
            
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:  # type 0 = text block
                    continue
                
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text:
                            y0 = span.get("y0", 0)
                            y1 = span.get("y1", 0)
                            x0 = span.get("x0", 0)
                            x1 = span.get("x1", 0)
                            size = span.get("size", 0)
                            
                            all_blocks.append(TextBlock(text, y0, y1, x0, x1, size))
                            full_text_parts.append(text)

        # Sort blocks by Y position (top to bottom)
        all_blocks.sort(key=lambda b: (b.y0, b.x0))
        
        # Build full text for compatibility
        full_text = "\n".join([b.text for b in all_blocks])

        # Identify sections
        sections = self._identify_sections(all_blocks)
        sections["full_text"] = full_text

        return sections

    def _identify_sections(self, blocks: List[TextBlock]) -> Dict[str, str]:
        """
        Identify sections based on section headers and Y-position grouping.
        """
        sections = {
            'shipper': '',
            'consignee': '',
            'agent': '',
            'handling': '',
            'cargo': '',
            'customs': '',
        }

        # Find section header blocks
        section_indices: Dict[str, int] = {}  # Maps section name to block index
        
        for i, block in enumerate(blocks):
            text_lower = block.text.lower()
            
            for section_name, headers in self.SECTION_HEADERS.items():
                for header in headers:
                    if header in text_lower and section_name not in section_indices:
                        section_indices[section_name] = i
                        break

        # Group blocks into sections
        # If a section header is found, collect blocks until the next header
        sorted_sections = sorted(section_indices.items(), key=lambda x: x[1])
        
        for section_idx, (section_name, block_idx) in enumerate(sorted_sections):
            start_idx = block_idx + 1  # Start after header
            
            # Find end: next section header or end of document
            if section_idx + 1 < len(sorted_sections):
                end_idx = sorted_sections[section_idx + 1][1]
            else:
                end_idx = len(blocks)
            
            # Collect text for this section
            section_text = []
            for i in range(start_idx, end_idx):
                if i < len(blocks):
                    # Stop if we hit another header
                    if any(h.lower() in blocks[i].text.lower() 
                           for headers in self.SECTION_HEADERS.values() 
                           for h in headers):
                        break
                    section_text.append(blocks[i].text)
            
            sections[section_name] = "\n".join(section_text).strip()

        return sections

    def extract_sections_from_text(self, text: str) -> Dict[str, str]:
        """
        Fallback: extract sections from flat text using pattern matching.
        Used when coordinate-based extraction is not available.
        """
        sections = {
            'shipper': '',
            'consignee': '',
            'agent': '',
            'handling': '',
            'cargo': '',
            'customs': '',
        }

        # Create a lookup map
        section_patterns = {
            'shipper': r'(?i)(shipper|from|sender)[^\n]*\n+(.*?)(?=\n(?:consignee|to|receiver|agent|handling))',
            'consignee': r'(?i)(consignee|to|receiver)[^\n]*\n+(.*?)(?=\n(?:agent|handling|cargo|charges|customs))',
            'agent': r'(?i)(agent|handling agent)[^\n]*\n+(.*?)(?=\n(?:handling|cargo|charges|customs))',
            'handling': r'(?i)handling[^\n]*\n+(.*?)(?=\n(?:cargo|charges|customs))',
            'cargo': r'(?i)(cargo|consolidation|said to contain)[^\n]*\n+(.*?)(?=\n(?:charges|customs|total|prepaid))',
            'customs': r'(?i)(customs|remarks)[^\n]*\n+(.*?)$',
        }

        import re
        for section_name, pattern in section_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                sections[section_name] = match.group(-1).strip() if match.lastindex else ''

        return sections
