#!/usr/bin/env python
"""Debug text extraction patterns"""

import re
from test_real_ocr import REAL_OCR

print("=" * 80)
print("SEARCHING FOR LABEL PATTERNS IN DOCUMENT")
print("=" * 80)

patterns = {
    "Shipper": r"Shipper[\s']*s\s+Name",
    "Consignee": r"Consignee[\s']*s?\s+[Nn]ame",
    "Agent": r"[Ii]ssuing Carriers? Agent",
    "Destination": r"Routing and Destination",
}

for label, pattern in patterns.items():
    if re.search(pattern, REAL_OCR, re.IGNORECASE):
        match = re.search(pattern, REAL_OCR, re.IGNORECASE)
        idx = match.start()
        context = REAL_OCR[max(0, idx-30):min(len(REAL_OCR), idx+150)]
        print(f"\n✓ Found '{label}' at position {idx}")
        print(f"  Context: {repr(context[:100])}")
    else:
        print(f"\n✗ NOT found: '{label}'")

print("\n" + "=" * 80)
print("ANALYZING SHIPPER SECTION")
print("=" * 80)

# Find "Shipper" text
shipper_idx = REAL_OCR.find("Shipper")
if shipper_idx >= 0:
    section = REAL_OCR[shipper_idx:shipper_idx+800]
    print(f"\nShipper section (first 800 chars):\n{section}\n")
    
    # Look for company patterns
    lines = section.split('\n')[:10]
    print(f"First 10 lines:")
    for i, line in enumerate(lines):
        print(f"  {i}: {repr(line)}")

print("\n" + "=" * 80)
print("ANALYZING CONSIGNEE SECTION")
print("=" * 80)

# Find "Consignee" text
consignee_idx = REAL_OCR.find("Consignee")
if consignee_idx >= 0:
    section = REAL_OCR[consignee_idx:consignee_idx+800]
    print(f"\nConsignee section (first 800 chars):\n{section}\n")
    
    # Look for company name
    lines = section.split('\n')[:10]
    print(f"First 10 lines:")
    for i, line in enumerate(lines):
        print(f"  {i}: {repr(line)}")
