#!/usr/bin/env python
"""Debug table extraction to understand the real OCR document structure"""

import re
from test_real_ocr import REAL_OCR

# Look for all numbers in the document
all_numbers = re.findall(r'\b(\d+[.,]?\d*)\b', REAL_OCR)
unique_numbers = sorted(set(all_numbers), key=lambda x: float(x.replace(',', '.')))

print("=" * 80)
print("ALL UNIQUE NUMBERS IN DOCUMENT (sorted by value)")
print("=" * 80)
for num in unique_numbers:
    # Find context (first 60 chars before and after)
    idx = REAL_OCR.find(num)
    context_before = REAL_OCR[max(0, idx-60):idx]
    context_after = REAL_OCR[idx+len(num):min(len(REAL_OCR), idx+len(num)+60)]
    print(f"\n{num:>12}  Context: ...{context_before.strip()[-30:]} [{num}] {context_after.strip()[:30]}...")

print("\n" + "=" * 80)
print("LOOKING FOR CHARGEABLE WEIGHT INDICATORS")
print("=" * 80)

# Search for "Chargeable" context
chargeable_matches = list(re.finditer(r'Chargeable[^.]*?(\d+[.,]?\d*)', REAL_OCR, re.IGNORECASE | re.DOTALL))
print(f"\nFound {len(chargeable_matches)} 'Chargeable Weight' patterns:")
for match in chargeable_matches:
    print(f"  Value: {match.group(1)}")
    print(f"  Context: {REAL_OCR[max(0, match.start()-50):min(len(REAL_OCR), match.end()+50)]}")

# Search for table weight columns
print("\n" + "=" * 80)
print("TABLE WEIGHT SECTION (around 'Weight')")
print("=" * 80)
weight_idx = REAL_OCR.find("Gross")
if weight_idx >= 0:
    section = REAL_OCR[weight_idx:weight_idx+1000]
    print(section[:500])
    
    # Extract numbers from this section
    nums_in_section = re.findall(r'\d+[.,]?\d*', section[:400])
    print(f"\nNumbers in table section: {nums_in_section}")

print("\n" + "=" * 80)
print("QUESTION: What should be the chargeable weight?")
print("=" * 80)
print(f"""
The document shows:
- Gross Weight: 12375.0 kg ✓ (clearly labeled)
- Pieces: 239 ✓ (clearly labeled)
- Chargeable Weight: ??? (not found in OCR)

Possible options:
1. The chargeable weight is NOT in the document
2. The chargeable weight is corrupted by OCR (looks like other numbers)
3. The chargeable weight should be calculated (volume-based, weight-based, etc.)
4. The chargeable weight value you expect (2750.0) is from a DIFFERENT document

The number 7889 found by parser comes from "38-4 7889/0015" which is an AGENT CODE, not a weight.

What is the correct chargeable weight for this shipment?
""")
