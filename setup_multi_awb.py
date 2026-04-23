#!/usr/bin/env python3
"""
Setup script for multi-AWB extraction feature.
Run this once: python setup_multi_awb.py
"""

import os
import sys
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.absolute()
APP_DIR = PROJECT_ROOT / "app"
TESTS_DIR = PROJECT_ROOT / "tests" / "unit"

print("=" * 70)
print("🚀 Multi-AWB Extraction Setup")
print("=" * 70)

# ============================================================================
# 1. CREATE: app/extraction/awb_document_splitter.py
# ============================================================================
print("\n[1/7] Creating app/extraction/awb_document_splitter.py...")

splitter_code = '''"""
Splits multi-AWB PDF text into individual AWB documents.
Uses AWB number (233-XXXXXXXX prefix) as document boundary marker.
"""

import re
from typing import List, Dict, Optional
from app.interpretation.awb_number import AWB_RE, _fix_ocr_digits


class AwbDocumentSplitter:
    """
    Splits PDF text containing multiple AWB documents.
    Each document is identified by its AWB number (233-XXXXXXXX format).
    Assumes AWB number appears near the start of each document.
    """

    def split_pdf_into_awb_documents(self, text: str) -> List[Dict[str, str]]:
        """
        Split PDF text into separate AWB documents.
        
        Args:
            text: Full PDF text (concatenated from all pages)
        
        Returns:
            List of dicts with keys:
            - awb_number: Extracted AWB number (e.g., "233-12345678")
            - text: Text content for this AWB document
            - start_pos: Character position in original text
            - end_pos: Character position in original text
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
            # No AWB found: return entire text as single document
            return [{'awb_number': None, 'text': text, 'start_pos': 0, 'end_pos': len(text)}]
        
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
            
            documents.append({
                'awb_number': match_info['awb_number'],
                'text': doc_text,
                'start_pos': doc_start,
                'end_pos': doc_end,
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
'''

try:
    splitter_path = APP_DIR / "extraction" / "awb_document_splitter.py"
    splitter_path.write_text(splitter_code)
    print("   ✅ Created app/extraction/awb_document_splitter.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 2. MODIFY: app/interpretation/awb_field_detector.py - Add extract_all()
# ============================================================================
print("[2/7] Modifying app/interpretation/awb_field_detector.py...")

detector_path = APP_DIR / "interpretation" / "awb_field_detector.py"
try:
    detector_code = detector_path.read_text()
    
    # Add extract_all method before the helper methods (_fallback_sections)
    if "def extract_all(" not in detector_code:
        extract_all_method = '''
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
'''
        # Insert before _fallback_sections
        insertion_point = detector_code.find("    def _fallback_sections(")
        if insertion_point != -1:
            detector_code = detector_code[:insertion_point] + extract_all_method + "\n" + detector_code[insertion_point:]
            detector_path.write_text(detector_code)
            print("   ✅ Added extract_all() to awb_field_detector.py")
        else:
            print("   ⚠️  Could not find insertion point in awb_field_detector.py")
    else:
        print("   ℹ️  extract_all() already exists in awb_field_detector.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 3. MODIFY: app/interpretation/awb_hybrid_extractor.py - Add extract_all()
# ============================================================================
print("[3/7] Modifying app/interpretation/awb_hybrid_extractor.py...")

hybrid_path = APP_DIR / "interpretation" / "awb_hybrid_extractor.py"
try:
    hybrid_code = hybrid_path.read_text()
    
    if "def extract_all(" not in hybrid_code:
        extract_all_hybrid = '''
    def extract_all(
        self, 
        texts: List[str], 
        sections_list: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract AWB fields from multiple text blocks using hybrid approach.
        
        Args:
            texts: List of text strings (one per AWB document)
            sections_list: Optional list of section dicts (parallel to texts)
        
        Returns:
            List of dicts, one per input text
        """
        results = []
        sections_list = sections_list or [None] * len(texts)
        
        for text, sections in zip(texts, sections_list):
            result = self.extract(text, sections)
            results.append(result)
        
        return results
'''
        # Insert before _merge_results
        insertion_point = hybrid_code.find("    def _merge_results(")
        if insertion_point != -1:
            hybrid_code = hybrid_code[:insertion_point] + extract_all_hybrid + "\n" + hybrid_code[insertion_point:]
            hybrid_path.write_text(hybrid_code)
            print("   ✅ Added extract_all() to awb_hybrid_extractor.py")
        else:
            print("   ⚠️  Could not find insertion point in awb_hybrid_extractor.py")
    else:
        print("   ℹ️  extract_all() already exists in awb_hybrid_extractor.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 4. MODIFY: app/interpretation/awb_normalizer.py - Add normalize_batch()
# ============================================================================
print("[4/7] Modifying app/interpretation/awb_normalizer.py...")

normalizer_path = APP_DIR / "interpretation" / "awb_normalizer.py"
try:
    normalizer_code = normalizer_path.read_text()
    
    if "def normalize_batch(" not in normalizer_code:
        normalize_batch_method = '''
    def normalize_batch(self, results: list) -> list:
        """
        Normalize multiple AwbData objects.
        
        Args:
            results: List of AwbData to normalize
        
        Returns:
            List of normalized AwbData
        """
        return [self.normalize(data) for data in results]
'''
        normalizer_code = normalizer_code.rstrip() + "\n" + normalize_batch_method + "\n"
        normalizer_path.write_text(normalizer_code)
        print("   ✅ Added normalize_batch() to awb_normalizer.py")
    else:
        print("   ℹ️  normalize_batch() already exists in awb_normalizer.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 5. REPLACE: app/pipelines/run_from_pdf.py
# ============================================================================
print("[5/7] Replacing app/pipelines/run_from_pdf.py...")

run_pdf_code = '''from pathlib import Path
from typing import List, Dict, Any, Optional
from ..ingestion.pdf_ingestor import PDFIngestor
from ..extraction.pdf_text_extractor import PDFTextExtractor
from ..extraction.awb_document_splitter import AwbDocumentSplitter
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer
from ..interpretation.awb_schema import AwbData
from ..integration.awb_repository import AwbRepository
from ..comparison.awb_diff_engine import AwbDiffEngine


def run(pdf_path: str) -> Dict[str, Any]:
    """
    Extract and process multiple AWBs from a PDF.
    
    Returns:
        Dict with keys:
        - extracted_awbs: List[AwbData] - normalized extracted AWBs
        - count: int - number of AWBs found
        - diffs: List[Dict] - diff results for each AWB vs iCargo
    """
    # Ingest PDF and extract text
    raw = PDFIngestor().from_path(pdf_path)
    text, _ = PDFTextExtractor().extract_text(raw)
    
    # Split text into individual AWB documents
    splitter = AwbDocumentSplitter()
    documents = splitter.split_pdf_into_awb_documents(text)
    
    # Filter to only prefix 233 (if needed)
    # documents = splitter.filter_documents_by_prefix(documents, prefix="233")
    
    # Extract AWB fields from each document
    doc_texts = [doc['text'] for doc in documents]
    detector = AwbFieldDetector()
    extraction_results = detector.extract_all(doc_texts)
    
    # Normalize results
    normalizer = AwbNormalizer()
    normalized_awbs: List[AwbData] = [
        normalizer.normalize(result.data) 
        for result in extraction_results
    ]
    
    # Generate diffs for each AWB
    repo = AwbRepository()
    diff_engine = AwbDiffEngine()
    diffs = []
    
    for awb_data in normalized_awbs:
        if awb_data.awb_prefix and awb_data.awb_serial:
            system_awb = repo.get_awb(awb_data.awb_prefix, awb_data.awb_serial)
            diff = diff_engine.diff(awb_data.dict(), system_awb)
            diffs.append({
                'awb_number': awb_data.awb_number,
                'diff': diff,
                'extracted': awb_data.dict(),
                'system': system_awb,
            })
        else:
            diffs.append({
                'awb_number': None,
                'diff': None,
                'extracted': awb_data.dict(),
                'system': None,
            })
    
    return {
        'extracted_awbs': normalized_awbs,
        'count': len(normalized_awbs),
        'diffs': diffs,
    }


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("Usage: python -m app.pipelines.run_from_pdf <path_to_pdf>")
    else:
        result = run(sys.argv[1])
        print(f"Extracted {result['count']} AWB(s)")
        print("\\nResults:")
        for awb_data in result['extracted_awbs']:
            print(f"  - {awb_data.awb_number}: {awb_data.shipper} → {awb_data.consignee}")
        print("\\nFull output:")
        print(json.dumps(result, indent=2, default=str))
'''

try:
    run_pdf_path = APP_DIR / "pipelines" / "run_from_pdf.py"
    run_pdf_path.write_text(run_pdf_code)
    print("   ✅ Replaced app/pipelines/run_from_pdf.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 6. MODIFY: app/ui/web_fastapi.py - Update imports and endpoint
# ============================================================================
print("[6/7] Modifying app/ui/web_fastapi.py...")

fastapi_path = APP_DIR / "ui" / "web_fastapi.py"
try:
    fastapi_code = fastapi_path.read_text()
    
    # Add imports if not present
    if "from ..extraction.awb_document_splitter import AwbDocumentSplitter" not in fastapi_code:
        # Find the import section and add new imports
        import_section = fastapi_code.split("app = FastAPI")[0]
        if "from typing import" not in import_section:
            import_section = 'from typing import List, Optional\n' + import_section
        else:
            import_section = import_section.replace(
                "from typing import",
                "from typing import List, Optional"
            )
        import_section += "from ..extraction.awb_document_splitter import AwbDocumentSplitter\n"
        
        rest = fastapi_code.split("app = FastAPI")[1]
        fastapi_code = import_section + "app = FastAPI" + rest
    
    # Replace the /extract/awb-from-pdf endpoint
    old_endpoint_start = fastapi_code.find("@app.post(\"/extract/awb-from-pdf\")")
    old_endpoint_end = fastapi_code.find("\n@app.", old_endpoint_start + 1)
    
    if old_endpoint_start != -1 and old_endpoint_end != -1:
        new_endpoint = '''@app.post("/extract/awb-from-pdf")
async def extract_awb_from_pdf(
    file: UploadFile = File(...),
    filter_prefix: Optional[str] = Query(None, description="Filter to specific AWB prefix (e.g., '233')")
):
    """Extract multiple AWBs from PDF."""
    if file.content_type not in ("application/pdf",):
        raise HTTPException(status_code=400, detail="PDF required")
    
    raw = await file.read()
    
    # Extract text
    text = PDFTextExtractor().extract_text(raw)[0]
    
    # Split into individual AWB documents
    splitter = AwbDocumentSplitter()
    documents = splitter.split_pdf_into_awb_documents(text)
    
    # Optional: filter by prefix
    if filter_prefix:
        documents = splitter.filter_documents_by_prefix(documents, prefix=filter_prefix)
    
    # Extract all AWBs
    doc_texts = [doc['text'] for doc in documents]
    extraction_results = AwbFieldDetector().extract_all(doc_texts)
    
    # Normalize and prepare response
    normalizer = AwbNormalizer()
    repo = AwbRepository()
    diff_engine = AwbDiffEngine()
    
    extracted_list = []
    diffs_list = []
    
    for result in extraction_results:
        normalized = normalizer.normalize(result.data)
        extracted_list.append({
            "awb_data": normalized.dict(),
            "confidences": [c.dict() for c in result.confidences]
        })
        
        # Generate diff if AWB number is valid
        if normalized.awb_prefix and normalized.awb_serial:
            system_awb = repo.get_awb(normalized.awb_prefix, normalized.awb_serial)
            diff = diff_engine.diff(normalized.dict(), system_awb)
            diffs_list.append({
                "awb_number": normalized.awb_number,
                "diff": diff,
                "extracted": normalized.dict(),
                "system": system_awb,
            })
    
    return {
        "count": len(extracted_list),
        "extracted_awbs": extracted_list,
        "diffs": diffs_list,
    }
'''
        
        fastapi_code = fastapi_code[:old_endpoint_start] + new_endpoint + fastapi_code[old_endpoint_end:]
        fastapi_path.write_text(fastapi_code)
        print("   ✅ Updated app/ui/web_fastapi.py")
    else:
        print("   ⚠️  Could not find endpoint to replace in web_fastapi.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# 7. CREATE: tests/unit/test_multi_awb_extraction.py
# ============================================================================
print("[7/7] Creating tests/unit/test_multi_awb_extraction.py...")

test_code = '''"""
Tests for multi-AWB PDF extraction.
"""
import pytest
from app.extraction.awb_document_splitter import AwbDocumentSplitter
from app.interpretation.awb_field_detector import AwbFieldDetector
from app.interpretation.awb_normalizer import AwbNormalizer


class TestAwbDocumentSplitter:
    """Test splitting PDF text into individual AWB documents."""
    
    def test_single_awb(self):
        """Test extraction of single AWB."""
        text = """
        233-12345678
        SHIPPER: Company A
        CONSIGNEE: Company B
        ORIGIN: MXP
        DESTINATION: FCO
        PIECES: 5
        WEIGHT: 100
        """
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] == '233-12345678'
        assert 'SHIPPER' in docs[0]['text']
    
    def test_multiple_awbs(self):
        """Test extraction of multiple AWBs from single PDF."""
        text = """
        233-12345678
        SHIPPER: Company A
        CONSIGNEE: Company B
        ORIGIN: MXP
        DESTINATION: FCO
        
        233-87654321
        SHIPPER: Company C
        CONSIGNEE: Company D
        ORIGIN: FCO
        DESTINATION: HKG
        """
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 2
        assert docs[0]['awb_number'] == '233-12345678'
        assert docs[1]['awb_number'] == '233-87654321'
        assert 'Company A' in docs[0]['text']
        assert 'Company C' in docs[1]['text']
    
    def test_no_awb(self):
        """Test handling of text with no AWB."""
        text = "Some random text without AWB numbers"
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] is None
    
    def test_filter_by_prefix(self):
        """Test filtering documents by AWB prefix."""
        text = """
        233-12345678
        Data A
        
        234-87654321
        Data B
        """
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        filtered = splitter.filter_documents_by_prefix(docs, prefix="233")
        
        assert len(filtered) == 1
        assert filtered[0]['awb_number'] == '233-12345678'


class TestMultiAwbFieldDetector:
    """Test field detection for multiple AWBs."""
    
    def test_extract_all(self):
        """Test extracting fields from multiple text blocks."""
        texts = [
            "233-12345678\\nSHIPPER: Company A\\nCONSIGNEE: Company B",
            "233-87654321\\nSHIPPER: Company C\\nCONSIGNEE: Company D"
        ]
        detector = AwbFieldDetector()
        results = detector.extract_all(texts)
        
        assert len(results) == 2
        assert results[0].data.awb_number == '233-12345678'
        assert results[1].data.awb_number == '233-87654321'


class TestMultiAwbNormalizer:
    """Test batch normalization."""
    
    def test_normalize_batch(self):
        """Test normalizing multiple AwbData objects."""
        from app.interpretation.awb_schema import AwbData
        
        data1 = AwbData(
            awb_prefix="233",
            awb_serial="12345678",
            origin="mxp",
            destination="fco"
        )
        data2 = AwbData(
            awb_prefix="234",
            awb_serial="87654321",
            origin="FCO",
            destination="HKG"
        )
        
        normalizer = AwbNormalizer()
        results = normalizer.normalize_batch([data1, data2])
        
        assert len(results) == 2
        assert results[0].origin == "MXP"
        assert results[1].origin == "FCO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''

try:
    test_path = TESTS_DIR / "test_multi_awb_extraction.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_code)
    print("   ✅ Created tests/unit/test_multi_awb_extraction.py")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("✅ Setup Complete!")
print("=" * 70)
print("\n📁 Files created/modified:")
print("   1. ✅ app/extraction/awb_document_splitter.py (NEW)")
print("   2. ✅ app/interpretation/awb_field_detector.py (modified)")
print("   3. ✅ app/interpretation/awb_hybrid_extractor.py (modified)")
print("   4. ✅ app/interpretation/awb_normalizer.py (modified)")
print("   5. ✅ app/pipelines/run_from_pdf.py (replaced)")
print("   6. ✅ app/ui/web_fastapi.py (modified)")
print("   7. ✅ tests/unit/test_multi_awb_extraction.py (NEW)")
print("\n🚀 Next steps:")
print("   1. Run tests: pytest tests/unit/test_multi_awb_extraction.py -v")
print("   2. Test with a multi-AWB PDF using Streamlit UI")
print("   3. Or test via API: POST /extract/awb-from-pdf with PDF file")
print("\n" + "=" * 70)