from pathlib import Path
from typing import List, Dict, Any, Optional
from ..ingestion.pdf_ingestor import PDFIngestor
from ..extraction.pdf_text_extractor import PDFTextExtractor
from ..extraction.awb_document_splitter import AwbDocumentSplitter
from ..extraction.awb_document_presplitter import AwbDocumentPreSplitter
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer
from ..interpretation.awb_schema import AwbData
from ..integration.awb_repository import AwbRepository
from ..comparison.awb_diff_engine import AwbDiffEngine


def run(pdf_path: str, use_presplitter: bool = True) -> Dict[str, Any]:
    """
    Extract and process multiple AWBs from a PDF.
    
    Args:
        pdf_path: Path to PDF file
        use_presplitter: If True, use AwbDocumentPreSplitter for cleaner document separation
                        (splits BEFORE OCR, avoiding cross-contamination)
    
    Returns:
        Dict with keys:
        - extracted_awbs: List[AwbData] - normalized extracted AWBs
        - count: int - number of AWBs found
        - diffs: List[Dict] - diff results for each AWB vs iCargo
        - document_ranges: List[Dict] - page ranges for each extracted document (if presplitter used)
    """
    # Ingest PDF
    raw = PDFIngestor().from_path(pdf_path)
    
    # --- Option 1: Use AwbDocumentPreSplitter (NEW - recommended) ---
    if use_presplitter:
        extractor = PDFTextExtractor()
        presplitter = AwbDocumentPreSplitter(extractor=extractor)
        
        # Pre-split into document ranges and extract text for each
        document_ranges = presplitter.presplit_pdf_with_text(raw, use_extractor=True)
        
        # Extract text from each document range separately
        doc_texts = [doc['text'] for doc in document_ranges]
        splitter = AwbDocumentSplitter()
        
    # --- Option 2: Use legacy single-pass extraction ---
    else:
        text, _ = PDFTextExtractor().extract_text(raw)
        
        # Split text into individual AWB documents
        splitter = AwbDocumentSplitter()
        documents = splitter.split_pdf_into_awb_documents(text)
        
        # Filter to only prefix 233 (if needed)
        # documents = splitter.filter_documents_by_prefix(documents, prefix="233")
        
        doc_texts = [doc['text'] for doc in documents]
        document_ranges = None
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
        'document_ranges': document_ranges,
    }


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("Usage: python -m app.pipelines.run_from_pdf <path_to_pdf>")
    else:
        result = run(sys.argv[1])
        print(f"Extracted {result['count']} AWB(s)")
        print("\nResults:")
        for awb_data in result['extracted_awbs']:
            print(f"  - {awb_data.awb_number}: {awb_data.shipper} -> {awb_data.consignee}")
        print("\nFull output:")
        print(json.dumps(result, indent=2, default=str))
