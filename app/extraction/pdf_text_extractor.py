# app/extraction/pdf_text_extractor.py
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional, Tuple, List

import pdfplumber
from PIL import Image

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\temp\Tessereact\tesseract.exe"


try:
    import fitz  # pymupdf
except Exception:
    fitz = None


@dataclass
class ExtractOptions:
    force_ocr: bool = False
    ocr_lang: str = "eng"          # puoi mettere "eng+ita"
    ocr_dpi: int = 200
    min_text_chars: int = 200      # sotto questa soglia → OCR fallback
    max_pages: Optional[int] = None  # None = tutte


class PDFTextExtractor:
    """
    1) prova estrazione testo con pdfplumber (born-digital)
    2) se testo insufficiente (o force_ocr) → OCR su immagini renderizzate con PyMuPDF + pytesseract
    """

    def __init__(self, options: Optional[ExtractOptions] = None):
        self.options = options or ExtractOptions()
        self._configure_tesseract_cmd_if_needed()

    def extract_text(self, raw_pdf: bytes) -> Tuple[str, bool]:
        # 1) direct text extraction
        direct_text = self._extract_with_pdfplumber(raw_pdf)
        if not self.options.force_ocr and len(direct_text.strip()) >= self.options.min_text_chars:
            return direct_text, False

        # 2) OCR fallback
        ocr_text = self._ocr_with_pymupdf(raw_pdf)
        return ocr_text, True

    def _extract_with_pdfplumber(self, raw_pdf: bytes) -> str:
        with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
            pages = pdf.pages
            if self.options.max_pages:
                pages = pages[: self.options.max_pages]
            texts = [(p.extract_text() or "") for p in pages]
        return "\n".join(texts)

    def _ocr_with_pymupdf(self, raw_pdf: bytes) -> str:
        if fitz is None:
            raise RuntimeError(
                "PyMuPDF (pymupdf) non installato. Esegui: pip install pymupdf"
            )

        doc = fitz.open(stream=raw_pdf, filetype="pdf")
        total_pages = doc.page_count
        max_pages = self.options.max_pages or total_pages
        max_pages = min(max_pages, total_pages)

        out: List[str] = []
        zoom = self.options.ocr_dpi / 72  # 72dpi base PDF
        mat = fitz.Matrix(zoom, zoom)

        for i in range(max_pages):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang=self.options.ocr_lang)
            out.append(text)

        return "\n".join(out)

    def _configure_tesseract_cmd_if_needed(self):
        import os
        import pytesseract

        # 1) Se hai una env var, usa quella
        env_cmd = os.getenv("TESSERACT_CMD")
        if env_cmd and os.path.exists(env_cmd):
            pytesseract.pytesseract.tesseract_cmd = env_cmd
            return

        # 2) Fallback: usa il tuo path noto
        custom = r"C:\temp\Tessereact\tesseract.exe"
        if os.path.exists(custom):
            pytesseract.pytesseract.tesseract_cmd = custom
            return
