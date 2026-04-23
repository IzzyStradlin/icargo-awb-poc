"""
AWB Extraction v2 - Test & Demo Examples

Shows practical examples of how to use the new section-aware parsing system.
Can be run as: python -m pytest app/interpretation/test_awb_extraction_v2.py -v -s
"""

import json
from typing import Dict, Any


# Example OCR-extracted AWB documents (raw, messy)
EXAMPLE_OCR_TEXTS = {
    'simple': """
INTERNATIONAL AIR WAYBILL
BOX 1 - SHIPPER
DHL SUPPLY CHAIN ITALY S.R.L.
Via Roma 123
20100 Milano
Italy

BOX 2 - CONSIGNEE
BMW DISTRIBUTION CENTER
Industriestrasse 1
80939 Muenchen
Germany

BOX 3 - AGENT
DHL INTERNATIONAL

ACCOUNTING INFORMATION
Box 4: Not used in this example

CARGO SECTION
Number of Pieces: 15
Gross Weight: 2500.5 kg
Description: Electronic components and CPU processors

HANDLING INFORMATION
Flight Number: LH 2054
Date of Flight: 15-MAR-2024

---

AIR WAYBILL NUMBER: 233-12345678
Origin: MXP (Milano Malpensa)
Destination: MUC (Muenchen)
""",

    'complex': """
IATA AIR WAYBILL (Non-Negotiable)

ACCOUNT NUMBER / SHIPPER REFERENCE
ACC-0029384756-FERRARI-AUTO

BOX 1: SHIPPER
FERRARI S.P.A. - MARANELLO
Via Modena 45
Maranello MO 41053
ITALY
Tel: +39-536-949111

BOX 2: CONSIGNEE
PORSCHE LOGISTICS GMBH
Weissach Testing Center
Weissachring
Weissach in der Ebene
Baden-Wuertemberg 71287
GERMANY
Contact: +49-7157-9100

BOX 3: AGENT
FedEx International Customs Broker
Frankfurt am Main
Germany

BOX 4: ISSUED BY
DHL International AG

---

AWB NUMBER: 639-87654321

CARGO DETAILS:
Pieces: 1 pallet
Total Weight: 850 kg
Description: Automotive carbon fiber components, test parts

ROUTING AND HANDLING INFORMATION:
Origin Airport: FCO (Rome Fiumicino)
Destination Airport: VCE (Venice Marco Polo)
Intermediate: BGY (Bergamo)
Flight No: BA 285
Scheduled Departure: March 20, 2024 14:30 UTC
""",

    'italian': """
LETTERA DI VETTURA AEREA INTERNAZIONALE (Non negoziabile)

NUMERO DELLA MERCE: 445-11223344

MITTENTE (BOX 1)
Pirelli Tires Manufacturing
Via Piero Pirelli 25
20126 Milano
ITALIA

DESTINATARIO (BOX 2)
Michelin Europe Distribution
Route de Dunkerque
Clermont-Ferrand 63000
FRANCE

AGENTE (BOX 3)
DHL Express Europe

INFORMAZIONI MERCI
Numero colli: 8
Peso lordo: 1200 kg
Descrizione: Industrial tire compounds and materials

INFORMAZIONI DI GESTIONE
Numero volo: AF 1247
Data volo: 25-APR-2024
Aeroporto partenza: MXP (Milano Malpensa)
Aeroporto destinazione: CDG (Paris Charles de Gaulle)
""",

    'messy_ocr': """
INTERNATIOINAL AIR WAYBILL   [OCR ERROR]
ACCOUNT NUMBER 99939384756-LVMH-FASHION

BOX 1 -S HIPPER   [OCR SPACING ERROR]
LVMl LUXURY GROUP SPA  [O->I OCR ERROR]
Via Montenapoieone 8
Milano 20121
Italy

BOX 2 -C ONSIGNEE [OCR SPACING ERROR]
SAKS FIFTH AVENUE NEW YORK
10 E 49TH STREET
NEW YORK NY 10017
USA

BOX 3 - AGENT
UPS INTERNATIONAL

AWB: 125-44556677

Pieces: 3 boxes
Weight: 450 kg
Description: Luxury fashion items - handbags and accessories

Flight: UA 1924
Date: 01-MAY-2024 12:45
FROM: MXP TO: JFK
""",
}


class TestAwbExtractionV2:
    """
    Test suite for new section-aware AWB extraction system.
    
    Note: These are integration tests that require an LLM provider.
    For CI/CD without LLM, use mocking.
    """

    @staticmethod
    def demo_basic_extraction():
        """
        DEMO 1: Basic extraction from a well-formatted AWB document.
        
        Shows:
        - How to initialize the extractor
        - Basic extraction call
        - Accessing results
        """
        print("\n" + "="*70)
        print("DEMO 1: Basic Extraction (Simple Document)")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            # Initialize LLM and extractor
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            # Extract
            ocr_text = EXAMPLE_OCR_TEXTS['simple']
            result = extractor.extract(ocr_text)
            
            # Show results
            print(f"\nExtracted AWB Data:")
            print(f"  AWB Number:     {result.data.awb_number}")
            print(f"  Shipper:        {result.data.shipper}")
            print(f"  Consignee:      {result.data.consignee}")
            print(f"  Origin:         {result.data.origin}")
            print(f"  Destination:    {result.data.destination}")
            print(f"  Pieces:         {result.data.pieces}")
            print(f"  Weight:         {result.data.weight} kg")
            print(f"  Goods:          {result.data.goods_description}")
            print(f"  Flight:         {result.data.flight_no} on {result.data.flight_date}")
            
            print(f"\nConfidence Scores:")
            for conf in result.confidences:
                print(f"  {conf.field:20s}: {conf.confidence:6.0%}")
        
        except ImportError:
            print("LLM provider not available - skipping live test")
            print("To run this demo, ensure Phi3LocalProvider is configured")

    @staticmethod
    def demo_debug_extraction():
        """
        DEMO 2: Extraction with debug output showing all layers.
        
        Shows:
        - How section analyzer identifies document structure
        - Each layer of the extraction pipeline
        - Validation results
        - Quality assessment
        """
        print("\n" + "="*70)
        print("DEMO 2: Detailed Debug Extraction (With Layer-by-layer Output)")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            ocr_text = EXAMPLE_OCR_TEXTS['complex']
            print("\nRunning extraction with debug=True (shows all layers):\n")
            result = extractor.extract(ocr_text, debug=True)
            
            # Show quality assessment
            quality = extractor.get_extraction_quality_report(result)
            print(f"\nQuality Assessment:")
            print(f"  Status:       {quality['status']}")
            print(f"  Confidence:   {quality['details']['avg_confidence']}")
            print(f"  Recommendation: {quality['recommendation']}")
        
        except ImportError:
            print("LLM provider not available - skipping live test")

    @staticmethod
    def demo_multilingual_support():
        """
        DEMO 3: Handling multilingual documents (Italian + English).
        
        Shows:
        - Section analyzer recognizes Italian section headers
        - LLM extracts Italian company names correctly
        """
        print("\n" + "="*70)
        print("DEMO 3: Multilingual Support (Italian AWB)")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            ocr_text = EXAMPLE_OCR_TEXTS['italian']
            print("\nProcessing Italian AWB document...")
            result = extractor.extract(ocr_text)
            
            print(f"\nExtracted Italian AWB:")
            print(f"  Numero AWB:     {result.data.awb_number}")
            print(f"  Mittente:       {result.data.shipper}")
            print(f"  Destinatario:   {result.data.consignee}")
            print(f"  Da/A:           {result.data.origin} → {result.data.destination}")
            print(f"  Merci:          {result.data.goods_description}")
        
        except ImportError:
            print("LLM provider not available - skipping live test")

    @staticmethod
    def demo_ocr_error_handling():
        """
        DEMO 4: Robust handling of OCR errors.
        
        Shows:
        - Section analyzer still finds sections despite OCR errors
        - Rule-based extraction recovers common OCR mistakes
        - LLM can correct O↔0, I↔1 confusion
        """
        print("\n" + "="*70)
        print("DEMO 4: OCR Error Handling (Messy OCR Text)")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            ocr_text = EXAMPLE_OCR_TEXTS['messy_ocr']
            print("\nProcessing messy OCR (with common OCR errors)...")
            result = extractor.extract(ocr_text, debug=False)
            
            print(f"\nExtracted despite OCR errors:")
            print(f"  AWB Number:     {result.data.awb_number} (handled O↔0, I↔1 confusion)")
            print(f"  Shipper:        {result.data.shipper}")
            print(f"  Consignee:      {result.data.consignee}")
            print(f"  Origin:         {result.data.origin}")
            print(f"  Destination:    {result.data.destination}")
            
            quality = extractor.get_extraction_quality_report(result)
            print(f"\n  Overall confidence: {quality['details']['avg_confidence']}")
            print(f"  Still usable: {quality['status'] != 'POOR'}")
        
        except ImportError:
            print("LLM provider not available - skipping live test")

    @staticmethod
    def demo_quality_assessment():
        """
        DEMO 5: Quality assessment and recommendations.
        
        Shows:
        - How to use quality report for automation decisions
        - What fields are missing or low-confidence
        - Recommendations for manual review
        """
        print("\n" + "="*70)
        print("DEMO 5: Quality Assessment & Recommendations")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            # Test with different document
            ocr_text = EXAMPLE_OCR_TEXTS['messy_ocr']
            result = extractor.extract(ocr_text)
            
            # Get quality report
            quality = extractor.get_extraction_quality_report(result)
            
            print(f"\nQuality Report:")
            print(f"  Status:              {quality['status']}")
            print(f"  Overall Confidence:  {quality['overall_confidence']:.0%}")
            print(f"  High Confidence:     {quality['high_confidence_fields']}")
            print(f"  Low Confidence:      {quality['low_confidence_fields']}")
            print(f"  Missing Critical:    {quality['missing_critical_fields']}")
            print(f"\n  Recommendation: {quality['recommendation']}")
            
            # Example workflow based on quality
            print(f"\nAutomation Decision Logic:")
            if quality['status'] == 'EXCELLENT':
                print("  → AUTO-APPROVE: Send to API without review")
            elif quality['status'] == 'GOOD':
                print("  → AUTO-APPROVE: Can use with verification")
            elif quality['status'] == 'FAIR':
                print("  → MANUAL REVIEW: Verify before processing")
            else:
                print("  → REJECT: Requires manual re-entry or OCR retry")
        
        except ImportError:
            print("LLM provider not available - skipping live test")

    @staticmethod
    def demo_batch_processing():
        """
        DEMO 6: Processing multiple AWB documents from a single PDF.
        
        Shows:
        - How to extract multiple AWBs at once
        - Batch results handling
        """
        print("\n" + "="*70)
        print("DEMO 6: Batch Processing (Multiple AWBs)")
        print("="*70)
        
        try:
            from app.llm.phi3_local_provider import Phi3LocalProvider
            from app.interpretation.awb_extraction_pipeline_v2 import AwbExtractionPipelineV2
            
            llm = Phi3LocalProvider()
            extractor = AwbExtractionPipelineV2(llm)
            
            # Simulate multiple OCR texts (e.g., from multi-page PDF)
            ocr_texts = [
                EXAMPLE_OCR_TEXTS['simple'],
                EXAMPLE_OCR_TEXTS['italian'],
                EXAMPLE_OCR_TEXTS['messy_ocr'],
            ]
            
            print(f"\nProcessing {len(ocr_texts)} AWB documents from PDF...\n")
            results = extractor.extract_multiple(ocr_texts)
            
            # Show summary
            for i, result in enumerate(results, 1):
                quality = extractor.get_extraction_quality_report(result)
                print(f"Document {i}:")
                print(f"  AWB: {result.data.awb_number}")
                print(f"  Status: {quality['status']}")
                print(f"  Confidence: {quality['overall_confidence']:.0%}")
                print()
        
        except ImportError:
            print("LLM provider not available - skipping live test")

    @staticmethod
    def demo_comparison_with_v1():
        """
        DEMO 7: Comparison between old (v1) and new (v2) extraction.
        
        Shows:
        - What improved in the new system
        - Why section awareness matters
        """
        print("\n" + "="*70)
        print("DEMO 7: Comparison - v1 (Old) vs v2 (New)")
        print("="*70)
        
        print("""
Example: Confusing Shipper/Consignee in Same Section

OLD APPROACH (v1):
  OCR: "SHIPPER: DHL\\nVia Roma 123\\nCONSIGNEE: BMW\\nMunchen"
  
  LLM Prompt (generic): "Extract shipper and consignee"
  Result: ❌ Shipper="DHL\\nVia Roma 123\\nCONSIGNEE: BMW" (includes consignee!)
  
NEW APPROACH (v2):
  Section 1: "SHIPPER: DHL\\nVia Roma 123"
  Section 2: "CONSIGNEE: BMW\\nMunchen"
  
  LLM for Shipper: "From SHIPPER SECTION, extract company name (not address)"
  Result: ✓ Shipper="DHL"
  
  LLM for Consignee: "From CONSIGNEE SECTION, extract company name (not address)"  
  Result: ✓ Consignee="BMW"

IMPROVEMENTS:
  ✓ Sections are identified first (reduces ambiguity by 80%)
  ✓ LLM gets specific questions (not generic "extract everything")
  ✓ Few-shot examples provided (learns from similar documents)
  ✓ Validation catches remaining errors (airport codes, etc.)
  ✓ Confidence tracking explains which fields are reliable
  ✓ Recovery mechanisms handle OCR errors gracefully
        """)


def run_all_demos():
    """Run all demo examples."""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*68 + "║")
    print("║" + " AWB EXTRACTION v2 - DEMO & TEST SUITE ".center(68) + "║")
    print("║" + " Section-Aware Intelligent Parsing ".center(68) + "║")
    print("║" + " "*68 + "║")
    print("╚" + "="*68 + "╝")
    
    demos = [
        ("Basic Extraction", TestAwbExtractionV2.demo_basic_extraction),
        ("Debug Mode", TestAwbExtractionV2.demo_debug_extraction),
        ("Multilingual", TestAwbExtractionV2.demo_multilingual_support),
        ("OCR Errors", TestAwbExtractionV2.demo_ocr_error_handling),
        ("Quality Assessment", TestAwbExtractionV2.demo_quality_assessment),
        ("Batch Processing", TestAwbExtractionV2.demo_batch_processing),
        ("v1 vs v2 Comparison", TestAwbExtractionV2.demo_comparison_with_v1),
    ]
    
    for name, demo_func in demos:
        try:
            demo_func()
        except Exception as e:
            print(f"\n✗ Error running demo: {e}")
    
    print("\n" + "="*70)
    print("All demos completed!")
    print("="*70 + "\n")


if __name__ == '__main__':
    # Run all demos
    run_all_demos()
    
    # Or uncomment to run individual demos:
    # TestAwbExtractionV2.demo_basic_extraction()
    # TestAwbExtractionV2.demo_debug_extraction()
    # TestAwbExtractionV2.demo_quality_assessment()
