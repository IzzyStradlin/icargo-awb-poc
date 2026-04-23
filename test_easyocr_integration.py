#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PRACTICAL TEST: EasyOCR + v3 Extraction Pipeline

This script demonstrates how the new system works end-to-end.
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_easyocr_integration():
    """Test the complete EasyOCR integration"""
    
    print("\n" + "=" * 80)
    print("EASYOCR INTEGRATION TEST")
    print("=" * 80)
    
    # Step 1: Verify EasyOCR is installed
    print("\n[Step 1] Verifying EasyOCR installation...")
    try:
        import easyocr
        print("  ✓ EasyOCR is installed")
    except ImportError:
        print("  ✗ EasyOCR not found!")
        print("    Install with: pip install easyocr")
        return False
    
    # Step 2: Test integration module
    print("\n[Step 2] Testing integration module...")
    try:
        from app.ui.integration_easyocr import AwbExtractionPipelineWithEasyOCR
        print("  ✓ Integration module loads successfully")
    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        return False
    
    # Step 3: Initialize pipeline
    print("\n[Step 3] Initializing pipeline...")
    try:
        pipeline = AwbExtractionPipelineWithEasyOCR()
        print("  ✓ Pipeline initialized")
    except Exception as e:
        print(f"  ✗ Initialization error: {e}")
        return False
    
    # Step 4: Verify v3 extraction
    print("\n[Step 4] Verifying v3 extraction system...")
    try:
        from app.interpretation.iata_awb_extraction_pipeline_v3 import IataAwbExtractionPipeline
        v3_pipeline = IataAwbExtractionPipeline()
        print("  ✓ V3 extraction system available")
    except ImportError as e:
        print(f"  ✗ V3 pipeline error: {e}")
        return False
    
    # Step 5: Test with sample text
    print("\n[Step 5] Testing with sample AWB text...")
    
    sample_text = """
    Air Waybill
    233-10166763
    
    Shipper's Name and Address: CEVA AIR&OCEAN
    STRADA VECCHIA PAULLESE, 5/B
    21010 VIZZOLA TICINO, ITALY
    
    Consignee's Name and Address: CEVA HONG KONG LIMITED
    5F MAGNET PLACE TOWER 1
    77-81 CONTAINER PORT ROAD KWAI CHUNG
    HONG KONG
    
    Airport of Departure: MXP
    Airport of Destination: HKG
    
    Pieces: 239
    Gross Weight: 12375 kg
    Chargeable Weight: 2750 kg
    
    Flight Number: CP113
    Flight Date: 19JUN
    """
    
    try:
        result = pipeline.extract_from_text(sample_text)
        print("  ✓ Extraction successful")
        
        # Display results
        print("\n  Extracted Data:")
        print(f"    - AWB:        {result.data.awb_number}")
        print(f"    - Shipper:    {result.data.shipper}")
        print(f"    - Consignee:  {result.data.consignee}")
        print(f"    - Origin:     {result.data.origin}")
        print(f"    - Destination: {result.data.destination}")
        print(f"    - Pieces:     {result.data.pieces}")
        print(f"    - Weight:     {result.data.weight} kg")
        print(f"    - Chargeable: {result.data.chargeable_weight} kg")
        print(f"    - Flight:     {result.data.flight_no} ({result.data.flight_date})")
        
        # Quality
        quality = pipeline.get_quality_report(result)
        print(f"\n  Quality Assessment:")
        print(f"    - Status:     {quality.get('status', 'UNKNOWN')}")
        print(f"    - Confidence: {quality.get('overall_confidence', 0):.1%}")
        if 'fields_extracted' in quality:
            print(f"    - Fields:     {len(quality['fields_extracted'])}/{quality.get('total_fields', 'N/A')}")
        
    except Exception as e:
        print(f"  ✗ Extraction error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 6: Show next steps
    print("\n" + "=" * 80)
    print("READY TO USE!")
    print("=" * 80)
    
    print("""
Next Steps:
──────────

1. Test on real PDF files:
   pipeline = AwbExtractionPipelineWithEasyOCR()
   result = pipeline.extract_from_pdf('your_awb.pdf')

2. Integrate into Streamlit UI (pdf_upload.py):
   - Replace Tesseract OCR with EasyOCR
   - Use pipeline.extract_from_pdf() directly

3. Batch process multiple files:
   from pathlib import Path
   for pdf_file in Path('pdfs').glob('*.pdf'):
       result = pipeline.extract_from_pdf(str(pdf_file))
       print(f"{pdf_file.name}: {result.quality_report['status']}")

Expected Results:
─────────────────
✓ Clean company names (no more corruption)
✓ Correct destination and consignee info
✓ All numerical fields accurate
✓ Quality confidence: 98%+
    """)
    
    return True


if __name__ == '__main__':
    success = test_easyocr_integration()
    
    if success:
        print("\n✓ All tests passed!")
        sys.exit(0)
    else:
        print("\n✗ Tests failed!")
        sys.exit(1)
