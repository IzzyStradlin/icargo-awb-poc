#!/usr/bin/env python3
"""Fix remaining steps with proper UTF-8 encoding"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
APP_DIR = PROJECT_ROOT / "app"
TESTS_DIR = PROJECT_ROOT / "tests" / "unit"

print("=" * 70)
print("Fixing remaining steps (UTF-8 encoding enabled)...")
print("=" * 70)

# ============================================================================
# 5. REPLACE: app/pipelines/run_from_pdf.py
# ============================================================================
print("\n[5/7] Replacing app/pipelines/run_from_pdf.py...")

run_pdf_code = """from pathlib import Path
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
    \"\"\"
    Extract and process multiple AWBs from a PDF.
    
    Returns:
        Dict with keys:
        - extracted_awbs: List[AwbData] - normalized extracted AWBs
        - count: int - number of AWBs found
        - diffs: List[Dict] - diff results for each AWB vs iCargo
    \"\"\"
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
            print(f"  - {awb_data.awb_number}: {awb_data.shipper} -> {awb_data.consignee}")
        print("\\nFull output:")
        print(json.dumps(result, indent=2, default=str))
"""

try:
    run_pdf_path = APP_DIR / "pipelines" / "run_from_pdf.py"
    run_pdf_path.write_text(run_pdf_code, encoding='utf-8')
    print("   OK Created app/pipelines/run_from_pdf.py")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

# ============================================================================
# 6. MODIFY: app/ui/web_fastapi.py - Update imports and endpoint
# ============================================================================
print("[6/7] Modifying app/ui/web_fastapi.py...")

fastapi_path = APP_DIR / "ui" / "web_fastapi.py"
try:
    fastapi_code = fastapi_path.read_text(encoding='utf-8')
    
    # Add imports if not present
    if "from ..extraction.awb_document_splitter import AwbDocumentSplitter" not in fastapi_code:
        lines = fastapi_code.split('\n')
        # Find where to insert imports (after existing imports, before app = FastAPI)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('from ') or line.startswith('import '):
                insert_idx = i + 1
            elif line.startswith('app = FastAPI'):
                break
        
        # Add new imports
        new_imports = [
            "from typing import List, Optional",
            "from ..extraction.awb_document_splitter import AwbDocumentSplitter",
        ]
        
        for imp in new_imports:
            if imp not in fastapi_code:
                lines.insert(insert_idx, imp)
                insert_idx += 1
        
        fastapi_code = '\n'.join(lines)
    
    # Replace the /extract/awb-from-pdf endpoint
    old_endpoint_start = fastapi_code.find("@app.post(\"/extract/awb-from-pdf\")")
    old_endpoint_end = fastapi_code.find("\n@app.", old_endpoint_start + 1)
    
    if old_endpoint_start != -1 and old_endpoint_end != -1:
        new_endpoint = """@app.post("/extract/awb-from-pdf")
async def extract_awb_from_pdf(
    file: UploadFile = File(...),
    filter_prefix: Optional[str] = Query(None, description="Filter to specific AWB prefix (e.g., '233')")
):
    \"\"\"Extract multiple AWBs from PDF.\"\"\"
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
"""
        
        fastapi_code = fastapi_code[:old_endpoint_start] + new_endpoint + fastapi_code[old_endpoint_end:]
        fastapi_path.write_text(fastapi_code, encoding='utf-8')
        print("   OK Updated app/ui/web_fastapi.py")
    else:
        print("   WARNING: Could not find endpoint to replace in web_fastapi.py")
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# 7. CREATE: tests/unit/test_multi_awb_extraction.py
# ============================================================================
print("[7/7] Creating tests/unit/test_multi_awb_extraction.py...")

test_code = """\"\"\"Tests for multi-AWB PDF extraction.\"\"\"
import pytest
from app.extraction.awb_document_splitter import AwbDocumentSplitter
from app.interpretation.awb_field_detector import AwbFieldDetector
from app.interpretation.awb_normalizer import AwbNormalizer


class TestAwbDocumentSplitter:
    def test_single_awb(self):
        text = '''
        233-12345678
        SHIPPER: Company A
        CONSIGNEE: Company B
        ORIGIN: MXP
        DESTINATION: FCO
        PIECES: 5
        WEIGHT: 100
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] == '233-12345678'
        assert 'SHIPPER' in docs[0]['text']
    
    def test_multiple_awbs(self):
        text = '''
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
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 2
        assert docs[0]['awb_number'] == '233-12345678'
        assert docs[1]['awb_number'] == '233-87654321'
        assert 'Company A' in docs[0]['text']
        assert 'Company C' in docs[1]['text']
    
    def test_no_awb(self):
        text = "Some random text without AWB numbers"
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] is None
    
    def test_filter_by_prefix(self):
        text = '''
        233-12345678
        Data A
        
        234-87654321
        Data B
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        filtered = splitter.filter_documents_by_prefix(docs, prefix="233")
        
        assert len(filtered) == 1
        assert filtered[0]['awb_number'] == '233-12345678'


class TestMultiAwbFieldDetector:
    def test_extract_all(self):
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
    def test_normalize_batch(self):
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
"""

try:
    test_path = TESTS_DIR / "test_multi_awb_extraction.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_code, encoding='utf-8')
    print("   OK Created tests/unit/test_multi_awb_extraction.py")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("SUCCESS! Remaining steps completed")
print("=" * 70)
print("\nFiles updated:")
print("   5. OK app/pipelines/run_from_pdf.py (replaced)")
print("   6. OK app/ui/web_fastapi.py (modified)")
print("   7. OK tests/unit/test_multi_awb_extraction.py (NEW)")
print("\nNext: Run tests with: pytest tests/unit/test_multi_awb_extraction.py -v")