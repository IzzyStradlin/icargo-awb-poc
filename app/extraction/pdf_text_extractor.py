# app/extraction/pdf_text_extractor.py
from __future__ import annotations

import io
import re
import warnings
from dataclasses import dataclass
from typing import Optional, Tuple, List

import pdfplumber

try:
    import fitz  # pymupdf
except Exception:
    fitz = None

# Tesseract — fast rule-based OCR (~2s/page on CPU)
try:
    import pytesseract as _tesseract
    from PIL import Image as _PILImage
    # Set explicit path for Windows installs where Tesseract is not on PATH
    import os as _os
    _TESS_CANDIDATES = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        _os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for _p in _TESS_CANDIDATES:
        if _os.path.isfile(_p):
            _tesseract.pytesseract.tesseract_cmd = _p
            break
    _TESSERACT_AVAILABLE = True
except Exception:
    _TESSERACT_AVAILABLE = False

# EasyOCR — deep-learning OCR, kept as last-resort fallback (~40s/page on CPU)
try:
    import easyocr as _easyocr
    warnings.filterwarnings('ignore')
    _EASYOCR_AVAILABLE = True
except Exception:
    _EASYOCR_AVAILABLE = False


@dataclass
class ExtractOptions:
    force_ocr: bool = False
    ocr_lang: str = "eng"
    ocr_dpi: int = 200             # 200 DPI balances speed and accuracy for Tesseract
    min_text_chars: int = 200      # below this per-page → OCR fallback
    max_pages: Optional[int] = None


# EasyOCR reader — only loaded if Tesseract is unavailable
_easyocr_reader: Optional[object] = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        if not _EASYOCR_AVAILABLE:
            raise RuntimeError("Neither pytesseract nor EasyOCR is available.")
        _easyocr_reader = _easyocr.Reader(['en', 'it'], gpu=False)
    return _easyocr_reader


def _auto_rotate_image(pil_img) -> "_PILImage.Image":
    """
    Detect page orientation via Tesseract OSD and rotate the image to upright.
    If OSD traineddata is not installed or detection fails, returns the image unchanged.
    """
    try:
        osd = _tesseract.image_to_osd(pil_img, config="--psm 0 --oem 0")
        match = re.search(r"Rotate:\s*(\d+)", osd)
        if match:
            angle = int(match.group(1))
            if angle != 0:
                # PIL rotate: positive = CCW; PDF OSD "Rotate" means CW correction needed
                pil_img = pil_img.rotate(360 - angle, expand=True)
    except Exception:
        pass  # OSD unavailable or unreliable — continue with original orientation
    return pil_img


def _ocr_page(img_array) -> str:
    """
    Run OCR on a numpy uint8 RGB array.
    Strategy:
      1. pytesseract  (fast: ~2s/page)  — with automatic orientation correction via OSD
      2. EasyOCR      (slow: ~40s/page) — only if Tesseract not installed
    """
    if _TESSERACT_AVAILABLE:
        pil_img = _PILImage.fromarray(img_array)
        # Auto-rotate if the page is landscape or upside-down (OSD detection)
        pil_img = _auto_rotate_image(pil_img)
        # PSM 6 = assume uniform block of text (good for AWB forms)
        # OEM 3 = default engine (LSTM)
        cfg = "--oem 3 --psm 6"
        lang = "eng+ita"
        return _tesseract.image_to_string(pil_img, lang=lang, config=cfg)

    # Fallback: EasyOCR with line-reconstruction
    reader = _get_easyocr_reader()
    results = reader.readtext(img_array)
    lines: List[List[Tuple[float, str]]] = []
    line_ys: List[float] = []
    y_tol = 20
    for bbox, text, conf in results:
        if conf < 0.3:
            continue
        text_x = sum(p[0] for p in bbox) / 4
        text_y = sum(p[1] for p in bbox) / 4
        placed = False
        for i, ln in enumerate(lines):
            if abs(line_ys[i] - text_y) <= y_tol:
                ln.append((text_x, text))
                placed = True
                break
        if not placed:
            lines.append([(text_x, text)])
            line_ys.append(text_y)
    sorted_lines = sorted(zip(line_ys, lines), key=lambda p: p[0])
    return '\n'.join(
        ' '.join(tok for _, tok in sorted(toks, key=lambda t: t[0]))
        for _, toks in sorted_lines
    )


class PDFTextExtractor:
    """
    Per-page hybrid extraction — generator-based for real-time UI progress.

    Tier 1 (native): PyMuPDF get_text() — milliseconds per page, no OCR needed
    Tier 2 (OCR):    pytesseract (~2s/page) → EasyOCR fallback (~40s/page)

    OCR only fires on pages where native extraction yields < _PER_PAGE_MIN_CHARS.
    For born-digital PDFs (standard MSC AWBs) OCR never runs.
    """

    _PER_PAGE_MIN_CHARS = 50  # chars below which a page is considered "scanned"

    def __init__(self, options: Optional[ExtractOptions] = None):
        self.options = options or ExtractOptions()

    def scan_pages(self, raw_pdf: bytes):
        """
        Generator: yields (page_num, total_pages, page_text, method) per page.
        method = "native" | "OCR-tesseract" | "OCR-easyocr"
        """
        import numpy as np

        with pdfplumber.open(io.BytesIO(raw_pdf)) as plumber_pdf:
            all_pages = plumber_pdf.pages
            if self.options.max_pages:
                all_pages = all_pages[: self.options.max_pages]
            total = len(all_pages)

            fitz_doc = None
            mat = None
            if fitz is not None:
                fitz_doc = fitz.open(stream=raw_pdf, filetype="pdf")
                zoom = self.options.ocr_dpi / 72
                mat = fitz.Matrix(zoom, zoom)

            try:
                for i, plumber_page in enumerate(all_pages):
                    # --- Tier 1: PyMuPDF native text ---
                    fitz_page = fitz_doc.load_page(i) if fitz_doc is not None else None
                    native = ""
                    if fitz_page is not None:
                        native = fitz_page.get_text() or ""
                    if not native.strip():
                        native = plumber_page.extract_text() or ""

                    if not self.options.force_ocr and len(native.strip()) >= self._PER_PAGE_MIN_CHARS:
                        # Append spatially-reconstructed routing annotation so that
                        # _extract_flight_number can parse the routing table correctly
                        # even when get_text() linearisation garbles the column grid.
                        if fitz_page is not None:
                            supplement = self._routing_supplement(fitz_page)
                            if supplement:
                                native += "\n" + supplement
                        yield i + 1, total, native, "native"
                        continue

                    # --- Tier 2: OCR (scanned page) ---
                    img = None
                    if fitz_page is not None:
                        pix = fitz_page.get_pixmap(matrix=mat, alpha=False)
                        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                            pix.height, pix.width, 3
                        )
                        ocr_text = _ocr_page(img)
                        method = "OCR-tesseract" if _TESSERACT_AVAILABLE else "OCR-easyocr"
                    else:
                        ocr_text = native  # can't OCR without PyMuPDF
                        method = "native"

                    # Append spatially-reconstructed routing supplement for OCR pages.
                    # image_to_data() word positions are correct even when
                    # image_to_string() reading order is garbled by column layout.
                    if _TESSERACT_AVAILABLE and img is not None:
                        pil_for_supplement = _PILImage.fromarray(img)
                        supplement = self._routing_supplement_from_image(pil_for_supplement)
                        if supplement:
                            ocr_text += "\n" + supplement

                    yield i + 1, total, ocr_text, method
            finally:
                if fitz_doc:
                    fitz_doc.close()

    # ------------------------------------------------------------------
    # Routing-table spatial reconstruction (native PDF + OCR image)
    # ------------------------------------------------------------------

    _KNOWN_IATA = frozenset({
        'MXP','FCO','HKG','JFK','LAX','LHR','CDG','AMS','FRA','ZRH',
        'MAD','BCN','MUC','VCE','LIN','BGY','TRN','PSA','NAP','BLQ',
        'SIN','NRT','ICN','PEK','PVG','SHA','BKK','KUL','CGK','SYD',
        'MEL','DXB','AUH','DOH','GRU','EZE','BOG','SCL','MEX','YYZ',
        'YVR','ORD','ATL','MIA','EWR','SFO','SEA','IAD','BOS',
        'CPT','JNB','NBO','CAI','CMB','DEL','BOM','CCU','KHI',
    })

    def _find_routing_row(self, word_positions: List[tuple]) -> str:
        """
        Given a flat list of (x, y_center, word) tuples (from either native PDF
        word extraction or Tesseract image_to_data), group words into visual rows
        and return a "ROUTING: ..." annotation if a routing data row is found.

        Detection strategy
        ------------------
        The IATA AWB routing data row always starts:
            {3-letter IATA destination}  {2-letter carrier code}  {flight+date} ...
        e.g.  HKG  CP  113/19  EUR  PPX  NVD  NCV

        We scan every reconstructed row for this structure.  This is more robust
        than anchoring on column headers (which appear in garbled form or collide
        with the legal boilerplate on the right side of the form).

        False-positive guard: require the second token to be exactly 2 uppercase
        letters (carrier code) AND the third token (if present) to be digit-led
        (flight number or "113/19" style).
        """
        if not word_positions:
            return ""

        # Group words into visual rows (y-tolerance ±8 px).
        rows: List[tuple] = []
        for x, yc, word in sorted(word_positions, key=lambda w: (round(w[1] / 8), w[0])):
            placed = False
            for row in rows:
                if abs(row[0] - yc) <= 8:
                    row[1].append((x, word))
                    placed = True
                    break
            if not placed:
                rows.append((yc, [(x, word)]))

        # Scan rows for the routing data pattern.
        for _yc, wlist in sorted(rows, key=lambda r: r[0]):
            wlist.sort(key=lambda w: w[0])
            tokens = [w for _, w in wlist]
            if len(tokens) < 2:
                continue
            t0 = tokens[0].upper().strip(".,|[]()' ")
            t1 = tokens[1].upper().strip(".,|[]()' ")
            # Match: first token = 3-letter IATA, second = 2-letter carrier code
            if (
                re.match(r'^[A-Z]{3}$', t0)
                and t0 in self._KNOWN_IATA
                and re.match(r'^[A-Z]{2}$', t1)
                and (len(tokens) < 3 or re.search(r'\d', tokens[2]))  # 3rd = digits
            ):
                return "ROUTING: " + " ".join(tokens)

        return ""

    def _routing_supplement(self, fitz_page) -> str:
        """
        Extract a "ROUTING: ..." annotation from a native (text-layer) PDF page
        using word-level bounding boxes from PyMuPDF get_text("words").

        PyMuPDF get_text() linearises multi-column grids and mangles the routing
        section.  get_text("words") returns every word with its (x0,y0,x1,y1)
        bounding box before linearisation, so spatial reconstruction is correct.
        """
        words = fitz_page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_no)
        if not words:
            return ""
        positions = [
            (x0, (y0 + y1) / 2, word)
            for x0, y0, x1, y1, word, *_ in words
            if re.search(r'[A-Za-z0-9]', word)
        ]
        return self._find_routing_row(positions)

    def _routing_supplement_from_image(self, pil_img) -> str:
        """
        Extract a "ROUTING: ..." annotation from a scanned-image page using
        pytesseract.image_to_data() word bounding boxes.

        For pure-image PDFs, Tesseract image_to_string() --psm 6 reads the whole
        page as a uniform block and mangles multi-column routing grids.
        image_to_data() returns each word's pixel bounding box BEFORE the
        reading-order reconstruction step, so spatial positions are correct.
        """
        if not _TESSERACT_AVAILABLE:
            return ""
        try:
            import pytesseract as _pt
            from pytesseract import Output
            data = _pt.image_to_data(
                pil_img,
                lang="eng",
                config="--oem 3 --psm 6",
                output_type=Output.DICT,
            )
        except Exception:
            return ""

        positions: List[tuple] = []
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if not word or int(data["conf"][i]) < 20:
                continue
            if not re.search(r'[A-Za-z0-9]', word):
                continue
            left = int(data["left"][i])
            top = int(data["top"][i])
            height = int(data["height"][i])
            positions.append((left, top + height / 2, word))

        return self._find_routing_row(positions)

    def extract_text(self, raw_pdf: bytes) -> Tuple[str, bool]:
        """Convenience wrapper — no progress feedback."""
        page_texts: List[str] = []
        used_ocr = False
        for _n, _t, text, method in self.scan_pages(raw_pdf):
            page_texts.append(text)
            if method.startswith("OCR"):
                used_ocr = True
        return "\n".join(page_texts), used_ocr

