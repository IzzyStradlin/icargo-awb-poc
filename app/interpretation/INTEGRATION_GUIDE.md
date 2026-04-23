"""
INTEGRATION GUIDE - How to use the new AWB Extraction v2 system

This guide shows how to integrate the section-aware intelligent parsing
into your existing application.
"""

# ============================================================================
# QUICK START
# ============================================================================

"""
The simplest way to use the new system:

    from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
    from app.llm.phi3_local_provider import Phi3LocalProvider
    
    # Initialize
    llm = Phi3LocalProvider()  # or use CohereLLMProvider
    extractor = AwbExtractionPipelineV2(llm)
    
    # Extract
    result = extractor.extract(ocr_text)
    
    # Use results
    print(result.data.awb_number)
    print(result.data.shipper)
    
    # Check quality
    quality = extractor.get_extraction_quality_report(result)
    if quality['status'] == 'EXCELLENT':
        # Auto-process
        pass
    else:
        # Manual review needed
        pass
"""

# ============================================================================
# INTEGRATION INTO EXISTING PIPELINES
# ============================================================================

"""
SCENARIO 1: Replace old LLM extractor in run_from_pdf.py
=====================================================

OLD CODE (run_from_pdf.py):
    from app.interpretation.awb_hybrid_extractor import AwbHybridExtractor
    from app.llm.phi3_local_provider import Phi3LocalProvider
    
    llm = Phi3LocalProvider()
    extractor = AwbHybridExtractor(llm)
    extracted_data = extractor.extract(ocr_text, sections=None)

NEW CODE:
    from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipeline
    from app.llm.phi3_local_provider import Phi3LocalProvider
    
    llm = Phi3LocalProvider()
    extractor = AwbExtractionPipeline(llm)
    result = extractor.extract(ocr_text, debug=False)
    
    # Access as dict (backward compatible)
    extracted_data = extractor.extract_to_dict(ocr_text)

Note: The new system returns AwbExtractionResult objects which contain:
- data: AwbData (same structure as before)
- confidences: List of confidence scores (NEW - useful for quality assessment)
- raw_text: Original OCR text (for reference)
"""

# ============================================================================
# INTEGRATION INTO UI (Streamlit)
# ============================================================================

"""
SCENARIO 2: Enhanced Streamlit UI with confidence display
==========================================================

# app/ui/web_streamlit.py

import streamlit as st
from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
from app.llm.phi3_local_provider import Phi3LocalProvider

# Initialize session state
if 'extractor' not in st.session_state:
    llm = Phi3LocalProvider()
    st.session_state.extractor = AwbExtractionPipelineV2(llm)

# Upload OCR text
ocr_text = st.text_area("Paste OCR-extracted AWB text", height=300)

if st.button("Extract AWB"):
    with st.spinner("Extracting..."):
        result = st.session_state.extractor.extract(ocr_text, debug=False)
    
    # Show extracted data
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Extracted Data")
        st.write(f"AWB: {result.data.awb_number}")
        st.write(f"Shipper: {result.data.shipper}")
        st.write(f"Consignee: {result.data.consignee}")
        st.write(f"Route: {result.data.origin} → {result.data.destination}")
    
    with col2:
        st.subheader("Confidence Scores")
        for conf in result.confidences:
            color = "green" if conf.confidence >= 0.85 else "orange" if conf.confidence >= 0.60 else "red"
            st.write(f":{color}[{conf.field}: {conf.confidence:.0%}]")
    
    # Show quality assessment
    quality = st.session_state.extractor.get_extraction_quality_report(result)
    
    if quality['status'] == 'EXCELLENT':
        st.success(f"✓ {quality['recommendation']}")
    elif quality['status'] == 'GOOD':
        st.info(f"ℹ {quality['recommendation']}")
    elif quality['status'] == 'FAIR':
        st.warning(f"⚠ {quality['recommendation']}")
    else:
        st.error(f"✗ {quality['recommendation']}")
    
    # Option to override
    if st.checkbox("Edit fields"):
        shipper = st.text_input("Shipper", value=result.data.shipper or "")
        consignee = st.text_input("Consignee", value=result.data.consignee or "")
        # ... more fields
"""

# ============================================================================
# INTEGRATION INTO API (FastAPI)
# ============================================================================

"""
SCENARIO 3: REST API endpoint for AWB extraction
=================================================

# app/ui/web_fastapi.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
from app.llm.phi3_local_provider import Phi3LocalProvider

app = FastAPI()
llm = Phi3LocalProvider()
extractor = AwbExtractionPipelineV2(llm)

class ExtractRequest(BaseModel):
    ocr_text: str
    debug: bool = False

class ExtractResponse(BaseModel):
    awb_number: str
    shipper: str
    consignee: str
    origin: str
    destination: str
    pieces: int
    weight: float
    goods_description: str
    flight_number: str
    flight_date: str
    confidences: dict
    quality_status: str
    quality_recommendation: str

@app.post("/api/extract-awb", response_model=ExtractResponse)
async def extract_awb(request: ExtractRequest):
    try:
        # Extract
        result = extractor.extract(request.ocr_text, debug=request.debug)
        
        # Get quality assessment
        quality = extractor.get_extraction_quality_report(result)
        
        # Build response
        return ExtractResponse(
            awb_number=result.data.awb_number,
            shipper=result.data.shipper,
            consignee=result.data.consignee,
            origin=result.data.origin,
            destination=result.data.destination,
            pieces=result.data.pieces,
            weight=result.data.weight,
            goods_description=result.data.goods_description,
            flight_number=result.data.flight_no,
            flight_date=result.data.flight_date,
            confidences={c.field: c.confidence for c in result.confidences},
            quality_status=quality['status'],
            quality_recommendation=quality['recommendation']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""

# ============================================================================
# ADVANCED: Quality-based routing
# ============================================================================

"""
SCENARIO 4: Automated routing based on extraction quality
==========================================================

def process_awb_smart(ocr_text: str):
    '''
    Smart AWB processing with quality-based routing:
    - EXCELLENT: Auto-process
    - GOOD: Process with review
    - FAIR: Manual review queue
    - POOR: Reject and request re-scan
    '''
    
    extractor = AwbExtractionPipelineV2(llm)
    result = extractor.extract(ocr_text)
    quality = extractor.get_extraction_quality_report(result)
    
    if quality['status'] == 'EXCELLENT':
        # Auto-process
        send_to_icargo_api(result.data)
        log_extraction("auto_approved", result, quality)
    
    elif quality['status'] == 'GOOD':
        # Add to review queue with notification
        add_to_review_queue(result, priority="low")
        log_extraction("needs_review", result, quality)
    
    elif quality['status'] == 'FAIR':
        # Alert user for manual review
        alert_user_manual_review(result, quality)
        add_to_manual_queue(result)
        log_extraction("manual_review", result, quality)
    
    else:  # POOR
        # Reject and request re-scan
        reject_awb(result, reason=quality['recommendation'])
        log_extraction("rejected", result, quality)
"""

# ============================================================================
# MIGRATION CHECKLIST
# ============================================================================

"""
Migrating from v1 (old) to v2 (new)?

Follow this checklist:

STEP 1: Update Imports
  ❌ from app.interpretation.awb_llm_extractor import AwbLlmExtractor
  ❌ from app.interpretation.awb_hybrid_extractor import AwbHybridExtractor
  ✓ from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2

STEP 2: Update Initialization
  ❌ extractor = AwbHybridExtractor(llm_provider)
  ✓ extractor = AwbExtractionPipelineV2(llm_provider)

STEP 3: Update Extraction Call
  ❌ result = extractor.extract(ocr_text, sections=None)
  ✓ result = extractor.extract(ocr_text)
  
  For dict output (backward compat):
  ✓ result_dict = extractor.extract_to_dict(ocr_text)

STEP 4: Update Result Access
  Before:
    extracted_data = {
        'awb_number': result['awb_number'],
        'shipper': result['shipper'],
        ...
    }
  
  After (object-oriented):
    result = extractor.extract(ocr_text)
    print(result.data.awb_number)
    print(result.data.shipper)
  
  Or (dict compatibility):
    extracted_data = extractor.extract_to_dict(ocr_text)

STEP 5: Add Quality Checks (NEW!)
  quality = extractor.get_extraction_quality_report(result)
  
  if quality['status'] == 'EXCELLENT':
      # Safe to auto-process
      pass
  else:
      # Requires review
      pass

STEP 6: Test
  Run tests with sample AWB documents
  Compare v1 vs v2 results
  Verify confidence scores make sense
  
STEP 7: Deploy
  Use gradual rollout:
  - Start with 10% of documents
  - Monitor quality metrics
  - Increase percentage over time
"""

# ============================================================================
# DEBUGGING & TROUBLESHOOTING
# ============================================================================

"""
DEBUGGING: Enable debug output to understand extraction process

    result = extractor.extract(ocr_text, debug=True)

This will show:
- Which sections were detected
- What rule-based extraction found
- What LLM extracted from each section
- Validation results
- Final merged results
- Overall confidence

COMMON ISSUES:

Issue: Shipper/Consignee still mixed up
→ Check: Is section analyzer identifying sections correctly?
→ Run: extractor.section_analyzer.debug_sections(ocr_text)
→ Fix: May need to add custom section patterns for your OCR format

Issue: Low confidence scores
→ Check: Is OCR quality poor?
→ Run: Check raw_text for OCR errors
→ Fix: Improve OCR preprocessing or retry scan

Issue: Airport codes not recognized
→ Check: Are codes in different format? (e.g., "MXP-B" instead of "MXP")
→ Fix: May need to add airport code normalization

Issue: LLM extractions are still wrong
→ Check: Are prompts clear enough?
→ Run: extractor.field_extractor.debug_sections_with_prompts(ocr_text)
→ Fix: Fine-tune few-shot examples or use better LLM
"""

# ============================================================================
# PERFORMANCE NOTES
# ============================================================================

"""
PERFORMANCE CHARACTERISTICS:

v1 (old hybrid):
- Rule-based: ~50ms
- LLM: ~5-20 seconds (depends on LLM)
- Total: ~5-20 seconds per AWB

v2 (new section-aware):
- Section analysis: ~50ms (fast regex-based)
- Rule-based: ~50ms (same as before)
- LLM section-aware: ~5-20 seconds (similar to v1, but more accurate)
- Validation: ~10ms
- Total: ~5-20 seconds per AWB (same as v1, but better quality)

KEY INSIGHT: No performance degradation, only quality improvement!

OPTIMIZATION OPTIONS:

1. Batch Processing:
   results = extractor.extract_multiple([text1, text2, text3])
   
2. Caching:
   - Cache section analysis results
   - Cache LLM responses for similar sections
   
3. Parallel Processing:
   - Use ThreadPoolExecutor to extract multiple AWBs in parallel
   
4. Local LLM Optimization:
   - Use smaller model (Phi-3 vs Phi-3.5)
   - Quantization (INT4 vs INT8)
   - GPU acceleration
"""

# ============================================================================
# MONITORING & METRICS
# ============================================================================

"""
RECOMMENDED METRICS TO TRACK:

Per extraction:
- Extraction quality status (EXCELLENT / GOOD / FAIR / POOR)
- Overall confidence score
- Fields with high/low confidence
- Missing critical fields
- Extraction time

Aggregated:
- % EXCELLENT extractions
- % GOOD extractions
- % requiring manual review
- % rejected
- Average confidence per field
- Most commonly missing fields
- Most commonly low-confidence fields

Use quality report for monitoring:

    quality = extractor.get_extraction_quality_report(result)
    metrics = {
        'quality_status': quality['status'],
        'overall_confidence': quality['overall_confidence'],
        'missing_fields': quality['missing_critical_fields'],
        'low_confidence_fields': quality['low_confidence_fields'],
        'extracted_count': quality['extracted_count']
    }
    
    log_metrics(metrics)  # Send to monitoring system
"""
