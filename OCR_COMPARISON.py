#!/usr/bin/env python
"""
Compare different free OCR engines for AWB documents

Options evaluated:
1. Tesseract (currently used) - traditional, good but struggles with complex layouts
2. EasyOCR - Deep learning based, handles complex layouts better
3. PaddleOCR - Fast, accurate for documents, multilingual
"""

import subprocess
import sys

print("=" * 80)
print("FREE OCR ENGINES COMPARISON")
print("=" * 80)

engines = {
    "EasyOCR": {
        "pip": "easyocr",
        "features": [
            "Deep learning based (CRAFT + CRNN)",
            "Excellent layout understanding",
            "Multilingual support",
            "Handles skewed/rotated text",
            "Good for form documents",
        ],
        "languages": "80+ including Italian, English, Chinese",
        "speed": "Medium (GPU recommended)",
        "accuracy": "Very High (95%+ on clean documents)",
    },
    "PaddleOCR": {
        "pip": "paddleocr",
        "features": [
            "Baidu's OCR engine",
            "Fast and lightweight",
            "Good for structured documents",
            "Handles tables",
            "Multilingual",
        ],
        "languages": "100+ languages",
        "speed": "Very Fast (CPU sufficient)",
        "accuracy": "High (92%+ on clean documents)",
    },
    "Tesseract": {
        "pip": "pytesseract",
        "features": [
            "Traditional OCR (pattern matching)",
            "Lightweight, fast",
            "Widely used",
            "Limited layout understanding",
        ],
        "languages": "100+ languages",
        "speed": "Very Fast",
        "accuracy": "Medium-High (85-90% on clean documents)",
    },
}

print("\n1️⃣  EasyOCR (Recommended)")
print("-" * 80)
for feature in engines["EasyOCR"]["features"]:
    print(f"  ✓ {feature}")
print(f"  Languages: {engines['EasyOCR']['languages']}")
print(f"  Speed: {engines['EasyOCR']['speed']}")
print(f"  Accuracy: {engines['EasyOCR']['accuracy']}")
print(f"  Install: pip install {engines['EasyOCR']['pip']}")

print("\n2️⃣  PaddleOCR (Fast Alternative)")
print("-" * 80)
for feature in engines["PaddleOCR"]["features"]:
    print(f"  ✓ {feature}")
print(f"  Languages: {engines['PaddleOCR']['languages']}")
print(f"  Speed: {engines['PaddleOCR']['speed']}")
print(f"  Accuracy: {engines['PaddleOCR']['accuracy']}")
print(f"  Install: pip install {engines['PaddleOCR']['pip']}")

print("\n3️⃣  Tesseract (Current)")
print("-" * 80)
for feature in engines["Tesseract"]["features"]:
    print(f"  ✓ {feature}")
print(f"  Languages: {engines['Tesseract']['languages']}")
print(f"  Speed: {engines['Tesseract']['speed']}")
print(f"  Accuracy: {engines['Tesseract']['accuracy']}")

print("\n" + "=" * 80)
print("RECOMMENDATION FOR AWB DOCUMENTS")
print("=" * 80)
print("""
✅ USE EasyOCR because:
   1. Deep learning handles complex AWB layouts better than Tesseract
   2. Understands table structures (important for quantity/weight tables)
   3. Better at preserving structure of form fields
   4. Multilingual (good for international AWB documents)
   5. Free and open source
   6. Can be improved with custom training if needed later

⚡ Strategy:
   1. Reprocess PDFs with EasyOCR
   2. Apply v3 label-based extractor to clean OCR text
   3. Table parser will handle remaining numerical data
   4. Expected improvement: 85-90% extraction quality → 98%+ quality
""")

print("\n" + "=" * 80)
print("NEXT STEPS")
print("=" * 80)
print("""
1. Install EasyOCR:
   pip install easyocr
   
2. Create OCR preprocessing module:
   app/ingestion/enhanced_pdf_ocr.py
   - Load PDF with PyPDF2
   - Extract images
   - Apply EasyOCR
   - Return clean text
   
3. Test on real AWB PDF:
   - Compare Tesseract output vs EasyOCR output
   - Measure quality improvement
   
4. Integrate into pipeline:
   - Replace Tesseract with EasyOCR in ingestion
   - Re-test v3 extractor with better OCR input
""")
