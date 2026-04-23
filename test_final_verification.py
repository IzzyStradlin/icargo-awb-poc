#!/usr/bin/env python
"""Final verification test for IATA AWB v3 extraction"""

from app.interpretation.iata_awb_extraction_pipeline_v3 import IataAwbExtractionPipeline
from app.interpretation.test_iata_awb_v3 import YOUR_DOCUMENT

def run_verification():
    pipeline = IataAwbExtractionPipeline()
    result = pipeline.extract(YOUR_DOCUMENT, debug=False)
    
    # Display results
    print('='*70)
    print('IATA AWB v3 - FINAL VERIFICATION TEST')
    print('='*70)
    
    print('\nEXTRACTION RESULTS:')
    print('-'*70)
    print(f'AWB:               {result.data.awb_number}')
    print(f'Shipper:           {result.data.shipper}')
    print(f'Consignee:         {result.data.consignee}')
    print(f'Agent:             {result.data.agent}')
    print(f'Origin:            {result.data.origin}')
    print(f'Destination:       {result.data.destination}')
    print(f'Pieces:            {result.data.pieces}')
    print(f'Gross Weight:      {result.data.weight} kg')
    print(f'Chargeable Weight: {result.data.chargeable_weight} kg')
    print(f'Goods:             {result.data.goods_description}')
    print(f'Flight:            {result.data.flight_no}')
    
    # Verification
    checks_passed = 0
    total_checks = 11
    
    print('\n' + '='*70)
    print('VERIFICATION CHECKLIST:')
    print('-'*70)
    
    # Check 1: AWB
    passed = result.data.awb_number == '233-10166763'
    print(f"{'[PASS]' if passed else '[FAIL]'} AWB Number: {result.data.awb_number}")
    checks_passed += passed
    
    # Check 2: Shipper
    passed = result.data.shipper and 'CEVA AIR' in result.data.shipper
    print(f"{'[PASS]' if passed else '[FAIL]'} Shipper: {result.data.shipper}")
    checks_passed += passed
    
    # Check 3: Consignee
    passed = result.data.consignee and 'HONG KONG' in result.data.consignee
    print(f"{'[PASS]' if passed else '[FAIL]'} Consignee: {result.data.consignee}")
    checks_passed += passed
    
    # Check 4: Agent
    passed = result.data.agent and 'CEVA' in result.data.agent
    print(f"{'[PASS]' if passed else '[FAIL]'} Agent: {result.data.agent}")
    checks_passed += passed
    
    # Check 5: Origin
    passed = result.data.origin == 'MXP'
    print(f"{'[PASS]' if passed else '[FAIL]'} Origin: {result.data.origin}")
    checks_passed += passed
    
    # Check 6: Destination
    passed = result.data.destination == 'HKG'
    print(f"{'[PASS]' if passed else '[FAIL]'} Destination: {result.data.destination}")
    checks_passed += passed
    
    # Check 7: Pieces
    passed = result.data.pieces == 239
    print(f"{'[PASS]' if passed else '[FAIL]'} Pieces: {result.data.pieces}")
    checks_passed += passed
    
    # Check 8: Gross Weight
    passed = result.data.weight == 12375.0
    print(f"{'[PASS]' if passed else '[FAIL]'} Gross Weight: {result.data.weight}")
    checks_passed += passed
    
    # Check 9: Chargeable Weight
    passed = result.data.chargeable_weight == 2750.0
    print(f"{'[PASS]' if passed else '[FAIL]'} Chargeable Weight: {result.data.chargeable_weight}")
    checks_passed += passed
    
    # Check 10: Flight Number
    passed = result.data.flight_no == 'CP113/19'
    print(f"{'[PASS]' if passed else '[FAIL]'} Flight Number: {result.data.flight_no}")
    checks_passed += passed
    
    # Check 11: Goods Description
    passed = result.data.goods_description and 'Consolidation' in result.data.goods_description
    print(f"{'[PASS]' if passed else '[FAIL]'} Goods: {result.data.goods_description}")
    checks_passed += passed
    
    # Summary
    print('\n' + '='*70)
    print(f'RESULT: {checks_passed}/{total_checks} checks PASSED')
    print('='*70)
    
    if checks_passed == total_checks:
        print('\nSUCCESS! All checks passed! v3 extraction is production-ready!')
        return True
    else:
        print(f'\nWarning: {total_checks - checks_passed} checks failed')
        return False

if __name__ == '__main__':
    import sys
    success = run_verification()
    sys.exit(0 if success else 1)
