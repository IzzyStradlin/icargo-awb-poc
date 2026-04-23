#!/usr/bin/env python
"""Debug flight number label matching"""

import re
from app.interpretation.iata_awb_label_extractor import IataAwbLabelExtractor
from app.interpretation.test_iata_awb_v3 import YOUR_DOCUMENT

# Check if label patterns match
patterns = [
    r'Requested Flight/Date',
    r'Requested Routing',
    r'Flight\s+Number',
    r'Flight\s+No',
]

text = 'Flight Number\nCP113/19'

print("Testing label patterns against 'Flight Number\\nCP113/19':")
for pattern in patterns:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    print(f'  Pattern "{pattern}": {" MATCH" if match else "NO MATCH"}')

# Test with full document
print("\nSearching for 'Flight Number' in full document:")
if 'Flight Number' in YOUR_DOCUMENT:
    idx = YOUR_DOCUMENT.find('Flight Number')
    print(f"  Found at index {idx}")
    print(f"  Context: ...{YOUR_DOCUMENT[max(0,idx-20):idx+60]}...")
else:
    print("  NOT FOUND")

# Test extractor
print("\nTesting extractor._find_label_position for 'requested_flight':")
extractor = IataAwbLabelExtractor()
pos = extractor._find_label_position(YOUR_DOCUMENT, 'requested_flight')
print(f"  Position: {pos}")

if pos is not None:
    print(f"  Context: ...{YOUR_DOCUMENT[pos:pos+80]}...")
