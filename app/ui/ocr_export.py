"""
Export raw OCR text to JSON or XML format.
Includes metadata about extraction method, pages, timestamps.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, Dict, List
import re

from app.interpretation.awb_number import extract_msc_awbs


class OcrExporter:
    """Export raw OCR/extracted text with metadata to JSON/XML formats."""

    def __init__(
        self,
        text: str,
        filename: str,
        used_ocr: bool = False,
        total_pages: Optional[int] = None,
        extraction_method: str = "hybrid",
    ):
        """
        Args:
            text: Raw extracted text from PDF
            filename: Original PDF filename
            used_ocr: Whether OCR was used (vs native text extraction)
            total_pages: Number of pages in PDF
            extraction_method: Method used ("hybrid", "tesseract", "easyocr", "native")
        """
        self.text = text
        self.filename = filename
        self.used_ocr = used_ocr
        self.total_pages = total_pages
        self.extraction_method = extraction_method
        self.extracted_at = datetime.now().isoformat()

    def _extract_awb_numbers(self) -> List[str]:
        """Extract all unique AWB numbers from text using MSC-specific pattern."""
        # Use the dedicated MSC MAWB extractor
        awb_numbers = extract_msc_awbs(self.text)
        return awb_numbers

    def _count_pages_in_text(self) -> int:
        """Estimate page breaks from text structure."""
        # Simple heuristic: count page separator patterns
        separators = len(re.findall(r"^[\s]*$", self.text, re.MULTILINE))
        # Conservative estimate
        if self.total_pages:
            return self.total_pages
        return max(1, len(self.text) // 5000)  # ~5000 chars per page

    def to_dict(self) -> Dict:
        """Convert to dict representation."""
        awb_numbers = self._extract_awb_numbers()

        return {
            "metadata": {
                "extracted_at": self.extracted_at,
                "filename": self.filename,
                "total_pages": self.total_pages or self._count_pages_in_text(),
                "used_ocr": self.used_ocr,
                "extraction_method": self.extraction_method,
                "text_length": len(self.text),
                "awb_count": len(awb_numbers),
            },
            "extracted_awbs": awb_numbers,
            "raw_text": self.text,
        }

    def to_json(self, pretty: bool = True) -> str:
        """Export to JSON format."""
        data = self.to_dict()
        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False)

    def to_xml(self) -> str:
        """Export to XML format."""
        root = ET.Element("ocr_export")

        # Metadata section
        metadata_elem = ET.SubElement(root, "metadata")
        data = self.to_dict()
        meta = data["metadata"]

        for key, value in meta.items():
            elem = ET.SubElement(metadata_elem, key)
            elem.text = str(value)

        # AWB numbers section
        awbs_elem = ET.SubElement(root, "extracted_awbs")
        for awb in data["extracted_awbs"]:
            awb_elem = ET.SubElement(awbs_elem, "awb")
            awb_elem.text = awb

        # Raw text section
        text_elem = ET.SubElement(root, "raw_text")
        text_elem.text = self.text

        # Format with indentation
        if hasattr(ET, 'indent'):
            ET.indent(root, space="  ")
            xml_str = ET.tostring(root, encoding='unicode')
        else:
            xml_str = ET.tostring(root, encoding='unicode')
        
        return xml_str if xml_str else ""

    def to_csv_summary(self) -> str:
        """Export AWB numbers as CSV (simple format)."""
        awb_numbers = self._extract_awb_numbers()
        lines = ["AWB_NUMBER"]
        lines.extend(awb_numbers)
        return "\n".join(lines)
