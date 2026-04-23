#!/usr/bin/env python
"""Debug consignee extraction"""

import re
from test_real_ocr import REAL_OCR

match = re.search(r"Consignee[\s']*s?\s+[Nn]ame\s+and\s+Address[:\s]+(.*)", REAL_OCR, re.IGNORECASE | re.DOTALL)
if match:
    after_label = match.group(1)
    lines = after_label.split('\n')
    print('First 20 lines after Consignee label:')
    for i, line in enumerate(lines[:20]):
        stripped = line.strip()
        print(f'{i}: {repr(stripped[:80] if len(stripped) > 80 else stripped)}')
        
        # Check conditions
        skip_checks = []
        if 'Account' in line:
            skip_checks.append("has 'Account'")
        if 'Itis agreed' in line or 'SUBJECT' in line:
            skip_checks.append("has T&C markers")
        if re.match(r'^\d+', line):
            skip_checks.append("starts with digit")
        
        if skip_checks:
            print(f'   → Skip: {", ".join(skip_checks)}')
        elif len(line.strip()) >= 5:
            print(f'   → GOOD CANDIDATE!')
