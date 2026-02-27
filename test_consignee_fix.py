#!/usr/bin/env python3
"""
Quick test script to verify consignee extraction fix.
Tests that:
1. Consignee is not extracted as shipper value
2. LLM fallback is used when rule-based returns the shipper
"""

import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(__file__))

from app.interpretation.awb_field_detector import AwbFieldDetector
from app.interpretation.awb_hybrid_extractor import AwbHybridExtractor


def test_consignee_extraction():
    """Test consignee extraction on a sample AWB text."""
    
    # Sample OCR text from AWB 233-10048065
    sample_text = """
Shipper's Name and Address
DSV S.P.A. 
Issued by ALISCARGO AIRLINES S.P.A. VIA DANTE 134 CORSO SEMPIONE 32/A 20154 MILAN - ITALY LIMITO DI PIOLTEL MI 20096 IT

Consignee's Name and Address
DSV AIR AND SEA LTD.
HONG KONG

Agent's IATA Code
38-4 7072/0190

Airport of Departure (Addr. of First Carrier) and Requested Routing
MALPENSA APT/MILANO
HKG
"""
    
    # Test 1: Field detector (rule-based) with shipper parameter
    print("=" * 60)
    print("Test 1: Rule-based extraction with shipper awareness")
    print("=" * 60)
    
    detector = AwbFieldDetector()
    result = detector.extract(sample_text, sections={})
    
    shipper = result.data.shipper
    consignee = result.data.consignee
    
    print(f"Extracted Shipper: {shipper}")
    print(f"Extracted Consignee: {consignee}")
    
    if consignee == shipper:
        print("❌ FAIL: Consignee equals shipper (extraction error)")
        return False
    elif consignee is None:
        print("ℹ️  INFO: Consignee is None (rule-based didn't match, LLM should provide it)")
    elif consignee == "DSV AIR AND SEA LTD.":
        print("✅ PASS: Correct consignee extracted")
        return True
    else:
        print(f"⚠️  WARNING: Unexpected consignee: {consignee}")
    
    # Test 2: Hybrid extraction (should use LLM when rule-based returns wrong value)
    print("\n" + "=" * 60)
    print("Test 2: Hybrid extraction with LLM fallback")
    print("=" * 60)
    
    hybrid = AwbHybridExtractor()
    hybrid_result = hybrid.extract(sample_text)
    
    hybrid_shipper = hybrid_result.get("shipper")
    hybrid_consignee = hybrid_result.get("consignee")
    
    print(f"Hybrid Shipper: {hybrid_shipper}")
    print(f"Hybrid Consignee: {hybrid_consignee}")
    
    if hybrid_consignee == hybrid_shipper:
        print("❌ FAIL: Hybrid consignee still equals shipper")
        return False
    elif hybrid_consignee is None:
        print("⚠️  WARNING: Hybrid consignee is None (LLM extraction failed)")
        return False
    else:
        print(f"✅ PASS: Hybrid consignee is: {hybrid_consignee}")
        if "DSV AIR AND SEA" in hybrid_consignee:
            print("✅ PASS: Contains expected company name")
            return True
        else:
            print(f"ℹ️  INFO: Different consignee extracted (may be correct if different from shipper): {hybrid_consignee}")
            return True


if __name__ == "__main__":
    try:
        success = test_consignee_extraction()
        if success:
            print("\n" + "=" * 60)
            print("✅ All tests passed!")
            print("=" * 60)
            sys.exit(0)
        else:
            print("\n" + "=" * 60)
            print("❌ Some tests failed")
            print("=" * 60)
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
