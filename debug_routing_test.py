"""Debug: show what image_to_data returns around the routing area."""
import sys, io
sys.path.insert(0, ".")

# Import extractor first — this sets pytesseract.pytesseract.tesseract_cmd
import app.extraction.pdf_text_extractor as _ext_mod

import numpy as np
import fitz
import pytesseract
from pytesseract import Output
from PIL import Image

pdf_path = "C:/Users/massimiliano.catapan/Downloads/AWB_1.pdf"
raw = open(pdf_path, "rb").read()

doc = fitz.open(stream=raw, filetype="pdf")
page = doc.load_page(0)
zoom = 200 / 72
mat = fitz.Matrix(zoom, zoom)
pix = page.get_pixmap(matrix=mat, alpha=False)
img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
pil_img = Image.fromarray(img_array)

data = pytesseract.image_to_data(pil_img, lang="eng", config="--oem 3 --psm 6", output_type=Output.DICT)

# Group words into rows and print all rows
word_positions = []
for i, word in enumerate(data["text"]):
    word = word.strip()
    if not word or int(data["conf"][i]) < 10:
        continue
    left = int(data["left"][i])
    top = int(data["top"][i])
    h = int(data["height"][i])
    word_positions.append((left, top + h/2, word, data["conf"][i]))

# Group by y
rows = {}
for x, y, word, conf in word_positions:
    y_bucket = round(y / 10) * 10
    rows.setdefault(y_bucket, []).append((x, word, conf))

print("All rows from image_to_data (y bucket → words):")
for y_bucket in sorted(rows):
    row_words = " | ".join(f"{w}(c={c})" for _, w, c in sorted(rows[y_bucket]))
    print(f"  y~{y_bucket:4.0f}: {row_words}")
