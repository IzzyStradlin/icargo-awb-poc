"""
Test & Demo - IATA AWB v3 Label-Based Extraction

This script tests the new label-based extraction on real IATA AWB documents.

To run:
    python -m pytest app/interpretation/test_iata_awb_v3.py -v -s
    
Or directly:
    python app/interpretation/test_iata_awb_v3.py
"""

# The exact OCR text from your document
# NOTE: Reformatted with better line breaks for extraction accuracy
YOUR_DOCUMENT = r"""233-10166763

Shipper's Name and Address
CEVA AIR&OCEAN ITALY S.P.A.
STRADA VECCHIA PAULLESE, 5/B E 5/A
21010, VIZZOLA TICINO, ITALY

Consignee's Name and Address
CEVA HONG KONG LIMITED
5 F MAGNET PLACE TOWER 1
77-81 CONTAINER PORT ROAD KWAI CHUNG
HONG KONG 00000 HK

Issuing Carriers Agent Name and City
CEVA AIR&OCEAN S.P.A.
PANTIGLIATE

Airport of Departure and Requested Routing
MALPENSA APT/MILANO

Routing and Destination
[to HKG

Pieces: 239

Nature and Quantity of Goods
Consolidation as per attached list
239 PCS

Gross Weight
12375.00

Chargeable Weight
2750.0

Flight Number
CP113/19
"""


def test_iata_v3_extraction():
    """
    Test the new v3 label-based extraction on the document.
    
    Expected results:
    ✓ AWB: 233-10166763
    ✓ Shipper: CEVA AIR&OCEAN ITALY S.P.A. (NOT with address)
    ✓ Consignee: CEVA HONG KONG LIMITED (NOT with address)
    ✓ Agent: CEVA AIR&OCEAN S.P.A.
    ✓ Origin: MXP (from MALPENSA APT/MILANO)
    ✓ Destination: HKG (from "To:" field)
    ✓ Pieces: 239
    ✓ Gross Weight: 12375.00
    ✓ Chargeable Weight: 2750.0 (NEW FIELD)
    ✓ Goods: Consolidation as per attached list...
    ✓ Flight: CP113/19 (new format support)
    """
    
    from app.interpretation.iata_awb_extraction_pipeline_v3 import IataAwbExtractionPipeline
    
    print("\n" + "="*80)
    print("TESTING IATA AWB v3 - Label-Based Extraction")
    print("="*80)
    
    pipeline = IataAwbExtractionPipeline()
    result = pipeline.extract(YOUR_DOCUMENT, debug=True)
    
    print("\n" + "="*80)
    print("EXTRACTION RESULTS")
    print("="*80)
    
    print(f"\n✓ AWB Number:        {result.data.awb_number}")
    print(f"{'✓' if result.data.awb_number == '233-10166763' else '✗'} Expected: 233-10166763")
    
    print(f"\n✓ Shipper:           {result.data.shipper}")
    print(f"{'✓' if result.data.shipper and 'CEVA AIR&OCEAN' in result.data.shipper else '✗'} Expected: CEVA AIR&OCEAN ITALY S.P.A. (without address)")
    
    print(f"\n✓ Consignee:         {result.data.consignee}")
    print(f"{'✓' if result.data.consignee and 'CEVA HONG KONG' in result.data.consignee else '✗'} Expected: CEVA HONG KONG LIMITED (without address)")
    
    print(f"\n✓ Agent:             {result.data.agent}")
    print(f"{'✓' if result.data.agent and 'CEVA AIR&OCEAN' in result.data.agent else '✗'} Expected: CEVA AIR&OCEAN S.P.A.")
    
    print(f"\n✓ Origin:            {result.data.origin}")
    print(f"{'✓' if result.data.origin == 'MXP' else '✗'} Expected: MXP (from MALPENSA)")
    
    print(f"\n✓ Destination:       {result.data.destination}")
    print(f"{'✓' if result.data.destination == 'HKG' else '✗'} Expected: HKG (from 'To:' field)")
    
    print(f"\n✓ Pieces:            {result.data.pieces}")
    print(f"{'✓' if result.data.pieces == 239 else '✗'} Expected: 239")
    
    print(f"\n✓ Gross Weight:      {result.data.weight}")
    print(f"{'✓' if result.data.weight == 12375.00 else '✗'} Expected: 12375.00 kg")
    
    print(f"\n✓ Chargeable Weight: {result.data.chargeable_weight}")
    print(f"{'✓' if result.data.chargeable_weight == 2750.0 else '✗'} Expected: 2750.0 kg (NEW FIELD)")
    
    print(f"\n✓ Goods Description: {result.data.goods_description}")
    print(f"{'✓' if result.data.goods_description and 'Consolidation' in result.data.goods_description else '✗'} Expected: Consolidation as per attached list...")
    
    print(f"\n✓ Flight Number:     {result.data.flight_no}")
    print(f"{'✓' if result.data.flight_no == 'CP113/19' else '⚠'} Expected: CP113/19")
    
    # Show all confidence scores
    print("\n" + "="*80)
    print("CONFIDENCE SCORES")
    print("="*80)
    
    for conf in result.confidences:
        status = "✓" if conf.confidence >= 0.85 else "⚠" if conf.confidence >= 0.60 else "✗"
        print(f"{status} {conf.field:20s}: {conf.confidence:6.0%}")
    
    # Quality report
    print("\n" + "="*80)
    print("QUALITY ASSESSMENT")
    print("="*80)
    
    quality = pipeline.get_extraction_quality_report(result)
    print(f"Status:              {quality['status']}")
    print(f"Overall Confidence:  {quality['overall_confidence']:.0%}")
    print(f"Recommendation:      {quality['recommendation']}")
    
    if quality['missing_critical_fields']:
        print(f"Missing Critical:    {quality['missing_critical_fields']}")
    
    # Verification checklist
    print("\n" + "="*80)
    print("VERIFICATION CHECKLIST")
    print("="*80)
    
    checks = {
        "AWB extracted correctly": result.data.awb_number == "233-10166763",
        "Shipper extracted (company name only, no address)": result.data.shipper and "CEVA AIR&OCEAN" in result.data.shipper and "STRADA" not in (result.data.shipper or ""),
        "Consignee extracted (company name only, no address)": result.data.consignee and "HONG KONG" in result.data.consignee and "CONTAINER PORT" not in (result.data.consignee or ""),
        "Agent extracted correctly": result.data.agent and "CEVA AIR&OCEAN" in result.data.agent,
        "Origin extracted as MXP": result.data.origin == "MXP",
        "Destination extracted as HKG": result.data.destination == "HKG",
        "Pieces extracted correctly": result.data.pieces == 239,
        "Gross Weight extracted correctly": result.data.weight == 12375.00,
        "Chargeable Weight extracted correctly": result.data.chargeable_weight == 2750.0,
        "Flight Number extracted as CP113/19": result.data.flight_no == "CP113/19",
        "Goods description extracted": result.data.goods_description is not None,
    }
    
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    
    for check_name, passed_check in checks.items():
        status = "✓ PASS" if passed_check else "✗ FAIL"
        print(f"{status}: {check_name}")
    
    print(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed! v3 extraction is working correctly!")
    elif passed >= total - 1:
        print(f"\n⚠️  {total - passed} check failed - minor issue to investigate")
    elif passed >= total - 2:
        print(f"\n⚠️  {total - passed} checks failed - one or two issues to fix")
    else:
        print(f"\n❌ {total - passed} checks failed - significant issues to fix")
    
    return result


if __name__ == '__main__':
    # Run the test
    test_iata_v3_extraction()
