"""
Splits multi-AWB PDF text into individual AWB documents.
Uses AWB number (233-XXXXXXXX prefix) as document boundary marker.
FILTERS: Only extracts MASTER AWB (with "Not negotiable Air Waybill Issued by" marker)
Ignores House AWBs (consolidation documents)
"""

import re
from typing import List, Dict, Optional
from app.interpretation.awb_number import AWB_RE, _fix_ocr_digits


class AwbDocumentSplitter:
    """
    Splits PDF text containing multiple AWB documents.
    Each document is identified by its AWB number (233-XXXXXXXX format).
    
    IMPORTANT: Only extracts MASTER AWB documents that contain the marker
    "Not negotiable Air Waybill Issued by" or similar master AWB indicators.
    Filters out House AWBs (consolidation documents).
    """
    
    # Markers that identify a Master AWB
    MASTER_AWB_MARKERS = [
        'Not negotiable Air Waybill Issued by',
        'Not negotiable Air Waybill',
        'AIR WAYBILL ISSUED BY',
        'MASTER AIR WAYBILL',
        'Master Air Waybill',
        'AIR WAYBILL - NOT NEGOTIABLE',
        'MAWB',
    ]
    
    # Markers that identify a House AWB (to exclude)
    HOUSE_AWB_MARKERS = [
        'HOUSE AIR WAYBILL',
        'House Air Waybill',
        'HAWB',
        'CONSOLIDATION',
        'Consolidate',
    ]

    def is_master_awb(self, text: str) -> bool:
        """Check if text block contains Master AWB marker"""
        for marker in self.MASTER_AWB_MARKERS:
            if marker.upper() in text.upper():
                return True
        return False
    
    def is_house_awb(self, text: str) -> bool:
        """Check if text block is a House AWB (to exclude)"""
        for marker in self.HOUSE_AWB_MARKERS:
            if marker.upper() in text.upper():
                return True
        return False

    def split_pdf_into_awb_documents(self, text: str) -> List[Dict[str, str]]:
        """
        Split PDF text into separate AWB documents.
        FILTERS to only MASTER AWBs.
        
        Args:
            text: Full PDF text (concatenated from all pages)
        
        Returns:
            List of dicts with keys:
            - awb_number: Extracted AWB number (e.g., "233-12345678")
            - text: Text content for this AWB document
            - start_pos: Character position in original text
            - end_pos: Character position in original text
            - is_master: Boolean indicating if this is a Master AWB
        """
        # Find all AWB numbers with their positions
        awb_matches = []
        for match in AWB_RE.finditer(text):
            prefix = _fix_ocr_digits(match.group(1))
            serial = _fix_ocr_digits(match.group(2))
            
            if prefix.isdigit() and serial.isdigit():
                awb_number = f"{prefix}-{serial}"
                awb_matches.append({
                    'awb_number': awb_number,
                    'start_pos': match.start(),
                    'end_pos': match.end(),
                })
        
        if not awb_matches:
            # No AWB found: check if entire text is Master AWB
            if self.is_master_awb(text):
                return [{'awb_number': None, 'text': text, 'start_pos': 0, 'end_pos': len(text), 'is_master': True}]
            else:
                return [{'awb_number': None, 'text': text, 'start_pos': 0, 'end_pos': len(text), 'is_master': False}]
        
        # Split text into sections based on AWB positions
        documents = []
        for i, match_info in enumerate(awb_matches):
            # Document starts at current AWB number position
            # and ends just before the next AWB number
            doc_start = match_info['start_pos']
            
            if i + 1 < len(awb_matches):
                # Next document starts at the next AWB number
                doc_end = awb_matches[i + 1]['start_pos']
            else:
                # Last document goes to end of text
                doc_end = len(text)
            
            doc_text = text[doc_start:doc_end].strip()
            
            # CHECK: Is this a Master AWB?
            is_master = self.is_master_awb(doc_text)
            is_house = self.is_house_awb(doc_text)
            
            documents.append({
                'awb_number': match_info['awb_number'],
                'text': doc_text,
                'start_pos': doc_start,
                'end_pos': doc_end,
                'is_master': is_master,
                'is_house': is_house,
            })
        
        return documents

    def filter_documents_by_prefix(
        self, 
        documents: List[Dict[str, str]], 
        prefix: str = "233"
    ) -> List[Dict[str, str]]:
        """
        Filter documents to only those matching a specific AWB prefix.
        
        Args:
            documents: List from split_pdf_into_awb_documents()
            prefix: AWB prefix to filter by (default: "233")
        
        Returns:
            Filtered list of documents
        """
        filtered = []
        for doc in documents:
            if doc['awb_number'] and doc['awb_number'].startswith(prefix):
                filtered.append(doc)
        return filtered if filtered else documents
    
    def filter_master_awbs_only(
        self,
        documents: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Filter to keep ONLY Master AWBs, excluding House AWBs.
        
        Args:
            documents: List from split_pdf_into_awb_documents()
        
        Returns:
            List containing only Master AWB documents
        """
        master_only = [doc for doc in documents if doc.get('is_master', False) and not doc.get('is_house', False)]
        return master_only if master_only else documents
