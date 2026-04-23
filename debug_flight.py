#!/usr/bin/env python
"""Test table parser directly on real OCR"""

from app.interpretation.awb_table_parser import AwbTableParser
from test_real_ocr import REAL_OCR

parser = AwbTableParser()

flight, date = parser.extract_flight_info(REAL_OCR)
print(f"Table Parser Flight Result: {flight}")
print(f"Table Parser Date Result: {date}")

# Debug: search for "CP113" in the document
import re
cp_matches = re.findall(r'CP\d+', REAL_OCR)
print(f"\nCP patterns found in document: {cp_matches}")

# Search for flight patterns
flight_patterns = re.findall(r'([A-Z]{2,3})\s*(\d{1,4})(?:/(\d{1,2}))?', REAL_OCR)
print(f"\nFlight-like patterns found: {flight_patterns[:20]}")  # First 20

# Look for "CP113/19" specifically
if "CP113/19" in REAL_OCR:
    idx = REAL_OCR.find("CP113/19")
    print(f"\nFound 'CP113/19' at position {idx}")
    print(f"Context: {REAL_OCR[max(0, idx-50):idx+60]}")
else:
    print("\n'CP113/19' NOT found in document!")
    
# Look for just "CP113"
if "CP113" in REAL_OCR:
    idx = REAL_OCR.find("CP113")
    print(f"\nFound 'CP113' at position {idx}")
    print(f"Context: {REAL_OCR[max(0, idx-50):idx+60]}")
else:
    print("\n'CP113' NOT found in document!")
