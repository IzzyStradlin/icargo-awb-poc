"""
AWB EXTRACTION v2 - Architecture and Design Document

This document explains the new intelligent section-aware AWB parsing system
that replaces the simple rule-based + LLM hybrid approach.

===== PROBLEM STATEMENT =====

Previous approach (v1):
- OCR extracts raw text without structure
- Rule-based extractor tries to find patterns everywhere
- LLM receives messy text and tries to guess field boundaries
- Result: LLM makes mistakes confusing related fields

Example of failure:
  OCR text: "DHL Supply Chain Italy\nVia Roma 123\n20100 Milano\nBMW Distribution..."
  LLM gets confused: shipper field may bleed into consignee
  LLM output: shipper="DHL Supply Chain Italy\nVia Roma 123\n20100 Milano\nBMW Distribution"
  → WRONG (includes address, consignee, etc.)

===== SOLUTION ARCHITECTURE =====

New approach (v2): Section-Aware Intelligent Parsing

The AWB document is ALWAYS structured the same way (IATA standard):
- Box 1: Shipper
- Box 2: Consignee  
- Box 3: Agent
- Box 4: Accounting Info
- Cargo Section: Pieces, weight, description
- Handling Section: Flight, date

Strategy:
1. FIRST: Identify sections (where does Shipper section end, Consignee begin?)
2. THEN: Ask specific questions about each section
3. MERGE: Combine rule-based (for structured) + LLM (for semantic)
4. VALIDATE: Ensure all data meets requirements
5. REPORT: Track confidence and quality

===== LAYER-BY-LAYER EXECUTION =====

LAYER 1: Document Structure Analysis
├─ Input: Raw OCR text
├─ Process: AwbSectionAnalyzer identifies sections using patterns
│           Looks for headers like "BOX 1", "SHIPPER", "CONSIGNEE", etc.
│           Also looks for Italian equivalents: "CONTA 1", "MITTENTE", etc.
├─ Output: { shipper: "...", consignee: "...", cargo: "...", handling: "..." }
└─ Benefit: Reduces ambiguity - LLM now knows which section is which

LAYER 2: Rule-Based Structured Field Extraction
├─ Input: Full text + sections
├─ Fields: AWB number, Origin, Destination, Pieces, Weight
│         (These have predictable, parseable formats)
├─ Method: Regex patterns + IATA code lookup
├─ Confidence: 0.85-0.98 (very reliable)
└─ Benefit: Fast, deterministic, no LLM needed for obvious fields

LAYER 3: LLM-Based Semantic Field Extraction
├─ Input: Relevant section text ONLY + specific question
├─ Fields: Shipper name, Consignee name, Goods description, Flight details
│         (These require semantic understanding)
├─ Method: Section-aware prompts with few-shot examples
│         "From SHIPPER section, extract ONLY company name (not address)"
│         Much more specific than generic prompts
├─ Confidence: 0.60-0.95 (depends on OCR quality)
└─ Benefit: Massively reduces ambiguity & errors vs. asking on raw text

LAYER 4: Validation & Recovery
├─ Validates extracted values:
│  ├─ Airport codes are exactly 3 uppercase letters
│  ├─ Pieces is valid integer
│  ├─ Weight is valid positive number
│  ├─ AWB format is XXX-YYYYYYYY
│  └─ Company names are reasonable (not too short, not too long)
├─ Attempts recovery for borderline cases
└─ Tracks which validations passed/failed

LAYER 5: Intelligent Merge & Reporting
├─ Merges rule-based + LLM results
├─ Uses validation results to resolve conflicts
├─ Prioritizes high-confidence fields
├─ Generates quality report
├─ Tracks extraction confidence per field
└─ Provides recommendations (Auto-use? Manual review? Reject?)

===== KEY IMPROVEMENTS vs. v1 =====

Dimension           | v1 (Old)              | v2 (New)
--------------------|----------------------|-------------------------
Ambiguity           | High (full text)     | Low (specific sections)
LLM context         | Generic              | Specific per field
Prompt quality      | Simple               | Complex with few-shot
Validation          | None                 | Rigorous per field
Error recovery      | None                 | Intelligent recovery
Confidence tracking | No                   | Yes, per field
Quality reporting   | No                   | Yes, with recommendations
Robustness to OCR   | Low                  | High (isolated by section)
Shipper/Consignee   | Often confused       | Properly separated

Example comparison:

OLD (v1):
  Prompt: "Extract shipper and consignee from this text"
  Text: [mixed shipper+consignee+address garbage]
  Result: shipper confused with consignee ❌

NEW (v2):
  Prompt for shipper: "From SHIPPER SECTION (Box 1), extract ONLY company name"
  Text: [just the shipper section]
  Prompt for consignee: "From CONSIGNEE SECTION (Box 2), extract ONLY company name"  
  Text: [just the consignee section]
  Result: Clean separation ✓

===== CODE STRUCTURE =====

Module                          | Purpose
--------------------------------|-----------------------------------------------
awb_section_analyzer.py         | LAYER 1: Identifies document sections
awb_field_detector.py           | LAYER 2: Rule-based extraction (existing)
awb_section_field_extractor.py  | LAYER 3: LLM section-aware extraction
awb_parsing_agent.py            | LAYER 4-5: Orchestrator, validation, merge
awb_extraction_pipeline_v2.py   | USER INTERFACE: High-level extraction API

===== USAGE EXAMPLE =====

from app.llm.phi3_local_provider import Phi3LocalProvider
from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2

# Initialize
llm = Phi3LocalProvider()
extractor = AwbExtractionPipelineV2(llm)

# Extract with debug info
result = extractor.extract(ocr_text, debug=True)

# Access results
print(f"AWB: {result.data.awb_number}")
print(f"Shipper: {result.data.shipper}")
print(f"Consignee: {result.data.consignee}")
print(f"Origin: {result.data.origin}")

# Check confidence
for conf in result.confidences:
    print(f"{conf.field}: {conf.confidence:.0%}")

# Get quality assessment
quality = extractor.get_extraction_quality_report(result)
print(f"Status: {quality['status']}")
print(f"Recommendation: {quality['recommendation']}")

===== DEBUG MODE =====

Run extraction with debug=True to see what's happening at each layer:

extractor.extract(ocr_text, debug=True)

Output will show:
[LAYER 1: Document Structure Analysis]
  Found sections: shipper, consignee, cargo, handling
  Section confidences...

[LAYER 2: Rule-Based Extraction]
  AWB Number: 233-12345678 (confidence: 0.98)
  Origin: MXP (confidence: 0.95)
  ...

[LAYER 3: LLM-Based Section-Aware Extraction]
  Shipper: DHL Supply Chain Italy (confidence: 0.92)
  Consignee: BMW Distribution (confidence: 0.88)
  ...

[LAYER 4: Validation]
  AWB format: ✓ valid
  Origin code: ✓ valid
  Weight: ✓ valid
  ...

[LAYER 5: Merged Results]
  Overall Confidence: 0.91 (91%)
  High Confidence Fields: [awb_number, origin, destination, ...]
  Low Confidence Fields: [goods_description]
  Missing Fields: []

===== WHEN TO USE v2 vs v1 =====

Use v2 (new):
✓ Production deployments (better accuracy)
✓ Automated processing (confidence tracking helps)
✓ When you need to understand extraction quality
✓ When OCR quality is variable
✓ Always for new development

Use v1 (old):
✗ Only for backward compatibility if needed
✗ Testing against old results

===== FUTURE ENHANCEMENTS =====

1. Multi-page AWBs: Detect and merge fields from multiple pages
2. Historical context: Use past successful extractions as reference
3. User corrections: Learn from user corrections in the UI
4. Active learning: Ask user to verify low-confidence fields
5. Fine-tuned LLM: Train on actual AWB documents for even better results
6. Template matching: Recognize specific AWB template variations
"""
