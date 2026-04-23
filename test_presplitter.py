"""
Test and demonstration of AwbDocumentPreSplitter.

Usage:
    python -m test_presplitter <path_to_pdf>

Shows:
1. PDF page ranges identified as separate documents
2. Fuzzy matching results for MAWB markers
3. Extracted AWB numbers per document
"""

import sys
import json
from pathlib import Path

from app.extraction.awb_document_presplitter import AwbDocumentPreSplitter
from app.extraction.pdf_text_extractor import PDFTextExtractor
from app.ingestion.pdf_ingestor import PDFIngestor


def test_presplitter_basic(pdf_path: str):
    """Test presplitter with basic extraction (no OCR)."""
    print("\n" + "=" * 70)
    print("AwbDocumentPreSplitter - BASIC TEST (no OCR)")
    print("=" * 70)

    raw = PDFIngestor().from_path(pdf_path)
    presplitter = AwbDocumentPreSplitter(extractor=None)

    ranges = presplitter.presplit_pdf_into_ranges(raw, use_extractor=False)

    print(f"\n✓ Found {len(ranges)} document(s)")
    for i, doc in enumerate(ranges, 1):
        print(f"\n  Document {i}:")
        print(f"    Pages: {doc['start_page']}-{doc['end_page']} ({doc['page_count']} pages)")
        print(f"    MAWB Start: {doc['is_mawb_start']}")
        print(f"    AWB Number: {doc.get('awb_number', 'NOT EXTRACTED')}")


def test_presplitter_with_text(pdf_path: str):
    """Test presplitter with text extraction."""
    print("\n" + "=" * 70)
    print("AwbDocumentPreSplitter - WITH TEXT EXTRACTION")
    print("=" * 70)

    raw = PDFIngestor().from_path(pdf_path)
    extractor = PDFTextExtractor()
    presplitter = AwbDocumentPreSplitter(extractor=extractor)

    documents = presplitter.presplit_pdf_with_text(raw, use_extractor=True)

    print(f"\n✓ Found {len(documents)} document(s)")
    for i, doc in enumerate(documents, 1):
        text_preview = doc["text"][:200].replace("\n", " ")
        print(f"\n  Document {i}:")
        print(f"    Pages: {doc['start_page']}-{doc['end_page']} ({doc['page_count']} pages)")
        print(f"    AWB Number: {doc.get('awb_number', 'NOT EXTRACTED')}")
        print(f"    Text preview: {text_preview}...")
        print(f"    Text length: {len(doc['text'])} chars")


def test_presplitter_detailed(pdf_path: str):
    """Test with detailed output about fuzzy matching."""
    print("\n" + "=" * 70)
    print("AwbDocumentPreSplitter - DETAILED ANALYSIS")
    print("=" * 70)

    raw = PDFIngestor().from_path(pdf_path)
    extractor = PDFTextExtractor()
    presplitter = AwbDocumentPreSplitter(extractor=extractor)

    # Get page texts
    page_texts = {}
    for page_num, _total, text, method in extractor.scan_pages(raw):
        page_texts[page_num] = text
        print(f"\n  Page {page_num}: {method} extraction ({len(text)} chars)")

        # Check for MAWB markers
        has_primary = presplitter._fuzzy_match(
            text, presplitter.MAWB_PRIMARY_MARKER, presplitter.FUZZY_TOLERANCE
        )
        if has_primary:
            print(f"    ✓ Found primary MAWB marker (fuzzy match, tolerance={presplitter.FUZZY_TOLERANCE})")

        for marker in presplitter.MAWB_FALLBACK_MARKERS:
            has_marker = presplitter._fuzzy_match(text, marker, presplitter.FUZZY_TOLERANCE)
            if has_marker:
                print(f"    ✓ Found fallback marker: {marker}")

        # Try AWB extraction
        awb = presplitter._extract_awb_number_from_page(text)
        if awb:
            print(f"    ✓ Extracted AWB: {awb}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m test_presplitter <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"\n📄 Testing AwbDocumentPreSplitter with: {pdf_path}")

    try:
        # Run tests
        test_presplitter_basic(pdf_path)
        test_presplitter_with_text(pdf_path)
        test_presplitter_detailed(pdf_path)

        print("\n" + "=" * 70)
        print("✓ All tests completed")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
