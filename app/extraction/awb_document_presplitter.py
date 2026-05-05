"""
Pre-split PDF into individual AWB documents BEFORE OCR.

Strategy:
1. Extract text from each PDF page (native or OCR)
2. Identify AWB boundaries using a dual-marker approach:
   - PRIMARY:   "Shipper's Name and Address" (fuzzy 0.72 tolerance)
   - SECONDARY: "Shipper's Account Number"   (fuzzy 0.75 tolerance)
3. Merge both marker sets and re-cluster within 500 chars
4. Assign pages to documents based on marker positions
5. Fall back to MAWB phrase markers or AWB-number splitting if no boundaries found

This avoids OCR contamination between documents.
"""

from typing import List, Dict, Optional
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from app.interpretation.awb_number import extract_msc_awbs


class AwbDocumentPreSplitter:
    """
    Pre-split PDF into logical AWB document chunks before text extraction.
    Each chunk is a page range belonging to one Master AWB + its House AWBs.
    """

    # Master AWB markers (primary and fallbacks)
    MAWB_PRIMARY_MARKER = "Not Negotiable Air Waybill Issued by"
    MAWB_FALLBACK_MARKERS = [
        "Not negotiable Air Waybill",
        "AIR WAYBILL ISSUED BY",
        "MASTER AIR WAYBILL",
        "Master Air Waybill",
        "AIR WAYBILL - NOT NEGOTIABLE",
    ]

    # Document boundary markers (appears at start of each AWB document)
    # PRIMARY: "Shipper's Name and Address"
    #   Box 1 field label. Present on every IATA AWB document header.
    #   Fuzzy tolerance 0.72 handles OCR variants like "Shipper's Name'and Address",
    #   "Shippers Name and Address", etc.  No CONSIGNEE filter: Box 1 and Box 3 are
    #   side-by-side on standard AWB forms, so "Consignee" appears on the same page.
    SHIPPER_NAME_MARKER = "Shipper's Name and Address"
    SHIPPER_NAME_TOLERANCE = 0.72

    # SECONDARY: "Shipper's Account Number" (shorter, slightly more OCR-robust but fewer hits)
    SHIPPER_ACCOUNT_MARKER = "Shipper's Account Number"
    SHIPPER_ACCOUNT_TOLERANCE = 0.75

    # Fuzzy match tolerance for MAWB phrase markers (Strategy 2 fallback)
    FUZZY_TOLERANCE = 0.85

    def __init__(self, extractor=None):
        """
        Args:
            extractor: PDFTextExtractor instance for page-by-page extraction.
                      If None, will use basic pdfplumber extraction.
        """
        self.extractor = extractor

    @staticmethod
    def _fuzzy_match(text: str, pattern: str, tolerance: float = 0.85) -> bool:
        """
        Fuzzy string matching for OCR-corrupted text.
        Returns True if pattern matches within tolerance.
        
        Args:
            text: Text to search in (converted to uppercase)
            pattern: Pattern to find (converted to uppercase)
            tolerance: Similarity threshold (0.0-1.0)
        
        Returns:
            True if pattern is found with at least `tolerance` similarity
        """
        text_upper = text.upper()
        pattern_upper = pattern.upper()

        # First try exact match
        if pattern_upper in text_upper:
            return True

        # Try fuzzy matching in sliding windows
        pattern_len = len(pattern_upper)
        for i in range(len(text_upper) - pattern_len + 1):
            window = text_upper[i : i + pattern_len]
            ratio = SequenceMatcher(None, window, pattern_upper).ratio()
            if ratio >= tolerance:
                return True

        return False

    def _presplit_by_awb_as_markers(
        self, page_texts: Dict[int, str], mawb_starts: Dict[int, bool]
    ) -> List[Dict[str, any]]:
        """
        Fallback strategy: use AWB numbers as MAWB markers if text markers fail.
        
        When a page contains a NEW AWB number (not seen before), treat it as MAWB start.
        This is more robust for OCR text where marker phrases are corrupted.
        """
        documents = []
        current_doc_start = None
        seen_awbs = set()  # Track AWBs we've seen to detect new ones

        for page_num in sorted(page_texts.keys()):
            page_text = page_texts[page_num]
            
            # Check if this page has a NEW AWB number
            current_awbs = set(extract_msc_awbs(page_text))
            new_awbs = current_awbs - seen_awbs
            
            if new_awbs and current_doc_start is not None:
                # Found NEW AWB number - close previous document, start new one
                documents.append({
                    "start_page": current_doc_start,
                    "end_page": page_num - 1,
                    "page_count": page_num - current_doc_start,
                    "is_mawb_start": True,
                    "awb_number": None,
                })
                current_doc_start = page_num
            elif current_doc_start is None:
                # First page or first with AWB
                current_doc_start = page_num
            
            seen_awbs.update(current_awbs)

        # Close final document
        if current_doc_start is not None:
            max_page = max(page_texts.keys())
            documents.append({
                "start_page": current_doc_start,
                "end_page": max_page,
                "page_count": max_page - current_doc_start + 1,
                "is_mawb_start": True,
                "awb_number": None,
            })

        return documents

    def _find_mawb_start_in_page(self, page_text: str) -> bool:
        """
        Check if page contains Master AWB start marker (fuzzy).
        Returns True if this page appears to start a new MAWB.
        """
        # Try primary marker
        if self._fuzzy_match(page_text, self.MAWB_PRIMARY_MARKER, self.FUZZY_TOLERANCE):
            return True

        # Try fallback markers
        for marker in self.MAWB_FALLBACK_MARKERS:
            if self._fuzzy_match(page_text, marker, self.FUZZY_TOLERANCE):
                return True

        return False

    def _find_shipper_name_markers(self, text: str) -> List[int]:
        """
        Find all positions where "Shipper's Name and Address" (Box 1) appears.

        This is the PRIMARY boundary marker for IATA AWB documents.  The OCR
        produces variants like "Shipper's Name'and Address", "Shippers Name and
        Address", etc.  A fuzzy tolerance of 0.72 reliably captures all such
        variants across different scan qualities.

        No CONSIGNEE filter is applied: on a standard AWB form Box 1 (Shipper)
        and Box 3 (Consignee) are side-by-side, so "Consignee" legitimately
        appears close to the shipper label on the same page.

        Args:
            text: Full OCR text from all pages concatenated.

        Returns:
            List of char indices where boundary markers are found (sorted, ascending).
        """
        marker = self.SHIPPER_NAME_MARKER.upper()
        text_upper = text.upper()
        marker_len = len(marker)

        raw_positions = []
        for i in range(len(text_upper) - marker_len + 1):
            window = text_upper[i : i + marker_len]
            ratio = SequenceMatcher(None, window, marker).ratio()
            if ratio >= self.SHIPPER_NAME_TOLERANCE:
                raw_positions.append(i)

        if not raw_positions:
            return []

        # FILTER 1: Reject windows that slide into "CONSIGNEE'S NAME AND ADDRESS".
        # When the fuzzy window starts inside the word CONSIGNEE (e.g. at "SIGNEE'S
        # NAME AND ADDRESS"), the tail "NAME AND ADDRESS" is enough to score ≥0.72.
        # Guard: check the 5-char pre-context for any CONSIGNEE fragment.
        #
        # FILTER 2: The window must START with a variant of "SHIPPER" (first 7 chars).
        # This eliminates tail-matches like "...CHGS NAME AND ADDRESS USE ONLY..."
        # where the window starts on "NAME AND ADDRESS" rather than on "SHIPPER".
        filtered_positions = []
        for pos in raw_positions:
            # Filter 1 – reject manifest column-header false positives.
            # Customs manifest headers put CONSIGNEE on the same table line as SHIPPER:
            #   "SHIPPER NAME AND ADDRESS  CONSIGNEE NAME AND ADDRESS  DELIVER TO..."
            # The distance between SHIPPER and CONSIGNEE in that line is ≤80 chars.
            # On a real AWB form, Box 3 (Consignee) is many lines and hundreds of
            # characters below the shipper label — never within 100 chars.
            # NOTE: pos may land on a '\n' char (fuzzy scan is char-by-char), so we
            # must NOT rely on find("\n", pos) — that would return pos itself.
            # A forward-only flat window is robust against this edge case.
            forward_100 = text_upper[pos : pos + 100]
            if any(s in forward_100 for s in ("CONSIG", "ONSIGN", "NSIGNE", "SIGNEE")):
                continue
            # Filter 2 – window must begin with a SHIPPER-like token
            first7 = text_upper[pos : pos + 7]
            if SequenceMatcher(None, first7, "SHIPPER").ratio() < 0.5:
                continue
            filtered_positions.append(pos)

        if not filtered_positions:
            return []

        # CLUSTER: group overlapping sliding-window hits into one boundary each.
        # The sliding window produces consecutive hits spanning at most len(marker)-1 = 24
        # chars for the same real occurrence. A radius of 50 is sufficient to collapse
        # all duplicates without risking eating a genuine second boundary on an adjacent
        # page with sparse OCR output (which can be as few as ~80 chars).
        cluster_radius = 50
        clustered = []
        last_pos = None
        for pos in sorted(filtered_positions):
            if last_pos is None or pos - last_pos > cluster_radius:
                clustered.append(pos)
            last_pos = pos

        return clustered

    def _find_shipper_account_markers(self, text: str) -> List[int]:
        """
        Find all positions (char indices) where "Shipper's Account Number" appears.
        Used as SECONDARY boundary marker when the primary (Name/Address) yields nothing.

        Strategy:
        1. Find "Shipper's Account Number" with 75% tolerance
        2. Filter out false positives: exclude matches near "Consignee" keyword
        3. Cluster nearby matches to identify document boundaries

        Args:
            text: Full OCR text from all pages concatenated

        Returns:
            List of char indices where markers found (sorted, ascending)
        """
        marker = self.SHIPPER_ACCOUNT_MARKER.upper()
        text_upper = text.upper()
        marker_len = len(marker)
        
        # Find raw positions using fuzzy match @ 75%
        raw_positions = []
        for i in range(len(text_upper) - marker_len + 1):
            window = text_upper[i : i + marker_len]
            ratio = SequenceMatcher(None, window, marker).ratio()
            if ratio >= self.SHIPPER_ACCOUNT_TOLERANCE:
                raw_positions.append(i)
        
        if not raw_positions:
            return []
        
        # FILTER: Exclude positions near "Consignee" (false positive detection)
        # If "Consignee" appears within +/-100 chars, skip this match
        filtered_positions = []
        for pos in raw_positions:
            context_start = max(0, pos - 100)
            context_end = min(len(text), pos + 100)
            context = text[context_start:context_end].upper()
            
            # Keep match only if "Consignee" is NOT in nearby context
            if "CONSIGNEE" not in context:
                filtered_positions.append(pos)
        
        if not filtered_positions:
            return []
        
        # CLUSTER: Group nearby matches (within 20 chars) into single markers
        clustered = []
        last_pos = None
        for pos in sorted(filtered_positions):
            if last_pos is None or pos - last_pos > 20:
                clustered.append(pos)
            last_pos = pos
        
        return clustered

    def _presplit_by_shipper_marker(self, page_texts: Dict[int, str]) -> List[Dict[str, any]]:
        """
        PRIMARY presplit strategy: dual-marker approach.

        Searches for two complementary markers and merges their results:
          - PRIMARY:   "Shipper's Name and Address" (present on most AWBs, OCR-robust)
          - SECONDARY: "Shipper's Account Number"   (fills gaps where primary is corrupted)

        This guarantees that even a single badly-scanned AWB in an otherwise clean PDF
        does not fall through the cracks.

        Returns:
            List of document ranges: [{'start_page': ..., 'end_page': ...}, ...]
        """
        if not page_texts:
            return []
        
        # Concatenate all pages with a known delimiter to track positions
        # Store: (char_start, char_end, page_start, page_end)
        page_ranges = []  # List of (char_offset, page_num)
        full_text = ""
        char_offset = 0
        
        for page_num in sorted(page_texts.keys()):
            page_text = page_texts[page_num]
            page_ranges.append((char_offset, page_num))
            full_text += page_text + "\n--- PAGE BREAK ---\n"
            char_offset = len(full_text)
        
        # Find all boundary markers using BOTH strategies, then merge.
        #
        # PRIMARY:   "Shipper's Name and Address" (0.72 tolerance)
        #   → present on most AWBs, OCR-robust
        #
        # SECONDARY: "Shipper's Account Number" (0.75 tolerance)
        #   → used to fill gaps where the primary label is corrupted/absent
        #   Example: OCR produces "> ogalMxe xP 140277562 - Shippers Account Number Not Negotiable"
        #            with no recognisable "Shipper's Name and Address" at all.
        #
        # Merging guarantees that even a single badly-scanned AWB in an otherwise
        # clean PDF does not fall through the cracks.
        primary_positions = self._find_shipper_name_markers(full_text)
        secondary_positions = self._find_shipper_account_markers(full_text)

        # Merge and re-cluster with radius 200 so that primary and secondary hits
        # for the SAME boundary (which may be up to ~150 chars apart in linearised OCR
        # of a 2-column AWB header) collapse into one, while still being small enough
        # not to eat a genuine second boundary when intermediate pages (e.g. a manifest)
        # produce sparse OCR output (as few as ~80 chars per page in the top-20% crop).
        combined = sorted(set(primary_positions) | set(secondary_positions))
        marker_positions: List[int] = []
        last_pos = None
        for pos in combined:
            if last_pos is None or pos - last_pos > 200:
                marker_positions.append(pos)
            last_pos = pos
        
        if not marker_positions:
            # No markers found - return single document with all pages
            return [
                {
                    "start_page": min(page_texts.keys()),
                    "end_page": max(page_texts.keys()),
                    "page_count": len(page_texts),
                    "is_mawb_start": True,
                    "awb_number": None,
                }
            ]
        
        # Convert char positions back to page numbers
        documents = []
        marker_pages = []
        
        for marker_char_pos in marker_positions:
            # Find which page this char position belongs to
            for page_range_idx, (char_offset, page_num) in enumerate(page_ranges):
                next_offset = (
                    page_ranges[page_range_idx + 1][0]
                    if page_range_idx + 1 < len(page_ranges)
                    else float("inf")
                )
                
                if char_offset <= marker_char_pos < next_offset:
                    marker_pages.append(page_num)
                    break
        
        # Do NOT deduplicate by page number: two AWBs can start on the same
        # physical page (e.g. when a landscape "Original" copy is very long and
        # the next AWB header starts within the same page). If we drop duplicates
        # here we silently lose one split and return 7 instead of 8.
        marker_pages = sorted(marker_pages)
        
        # Build document ranges: each marker starts a new document.
        # When two consecutive markers share the same page (same-page collision),
        # the first document ends on that page and the second also starts there —
        # both documents get that page's text, which is acceptable.
        for i, start_page in enumerate(marker_pages):
            # End page is the page before next marker, or the last page.
            # If next marker is on the SAME page, end_page == start_page (single-page doc).
            if i + 1 < len(marker_pages):
                next_start = marker_pages[i + 1]
                end_page = max(start_page, next_start - 1)
            else:
                end_page = max(page_texts.keys())
            
            documents.append(
                {
                    "start_page": start_page,
                    "end_page": end_page,
                    "page_count": end_page - start_page + 1,
                    "is_mawb_start": True,
                    "awb_number": None,
                }
            )
        
        return documents

    def _extract_awb_number_from_page(self, page_text: str) -> Optional[str]:
        """Extract FIRST MSC AWB number (233-XXXXXXXX) from page text using strict MSC regex."""
        # Use dedicated MSC extractor (strict: only 233-XXXXXXXX, filters out VAT/tax numbers)
        awbs = extract_msc_awbs(page_text)
        return awbs[0] if awbs else None

    def _extract_awb_number_from_document_block(
        self, doc: Dict[str, any], page_texts: Dict[int, str]
    ) -> Optional[str]:
        """
        Extract the best AWB number from the whole split document block.

        Rationale:
        OCR can corrupt the header line near the marker, but a valid 233-XXXXXXXX
        often still appears somewhere else in the same block. Search the entire
        block first, then fall back to the first pages only if needed.
        """
        # Try first page only first — the AWB number on the form header is always
        # on the first page of the split, and searching the whole block risks
        # picking up a different AWB from a preceding page that shares the same
        # physical PDF page as this document's start.
        first_page_text = page_texts.get(doc["start_page"], "")
        first_page_awbs = extract_msc_awbs(first_page_text)
        if first_page_awbs:
            # If the first page contains multiple AWBs (e.g. a manifest page bleeds
            # into the next AWB form), prefer the one that appears LAST — it will be
            # the AWB number printed at the top of the new form, not a reference to
            # the previous manifest.
            return first_page_awbs[-1]

        # Fallback: search the full block text
        block_text = "\n".join(
            page_texts.get(page_num, "")
            for page_num in range(doc["start_page"], doc["end_page"] + 1)
        )
        awbs = extract_msc_awbs(block_text)
        if awbs:
            return awbs[0]

        return None

    def presplit_pdf_into_ranges(
        self, raw_pdf: bytes, use_extractor: bool = True
    ) -> List[Dict[str, any]]:
        """
        Analyze PDF and return document ranges (page numbers).

        Strategy (in order of priority):
        1. PRIMARY: "Shipper's Account Number" marker (fuzzy match, most robust)
        2. SECONDARY: "Not Negotiable Air Waybill" marker (if primary fails)
        3. TERTIARY: AWB number detection (fallback if only 1 doc found)

        Args:
            raw_pdf: PDF bytes
            use_extractor: If True, use self.extractor for OCR.
                          If False, use basic pdfplumber extraction.

        Returns:
            List of dicts:
            {
                'start_page': int (1-indexed),
                'end_page': int (1-indexed, inclusive),
                'awb_number': str or None,
                'is_mawb_start': bool,
                'page_count': int,
            }
        """
        if not pdfplumber:
            raise ImportError("pdfplumber is required for PDF analysis")

        # Extract text from each page
        page_texts = {}  # page_num (1-indexed) -> text

        if use_extractor and self.extractor:
            # Use provided extractor (supports OCR)
            for page_num, total, text, method in self.extractor.scan_pages(raw_pdf):
                page_texts[page_num] = text
        else:
            # Basic pdfplumber extraction (no OCR)
            with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    text = page.extract_text() or ""
                    page_texts[page_num] = text

        if not page_texts:
            return []

        # ===== STRATEGY 1: Try Shipper's Account Number marker (PRIMARY) =====
        documents = self._presplit_by_shipper_marker(page_texts)
        if len(documents) > 1:
            # Successfully found multiple documents using shipper marker
            self._enrich_documents_with_awbs(documents, page_texts)
            documents = self._merge_same_awb_documents(documents)
            return documents

        # ===== STRATEGY 2: Fallback to MAWB markers (SECONDARY) =====
        documents = []
        mawb_starts = {}  # page_num -> True if starts MAWB
        for page_num in sorted(page_texts.keys()):
            text = page_texts[page_num]
            mawb_starts[page_num] = self._find_mawb_start_in_page(text)

        # Build document ranges from MAWB markers
        current_doc_start = None
        current_doc_is_mawb = False

        for page_num in sorted(page_texts.keys()):
            if mawb_starts[page_num]:
                # Start of new MAWB
                if current_doc_start is not None:
                    documents.append(
                        {
                            "start_page": current_doc_start,
                            "end_page": page_num - 1,
                            "page_count": page_num - current_doc_start,
                            "is_mawb_start": current_doc_is_mawb,
                            "awb_number": None,
                        }
                    )

                # Start new MAWB
                current_doc_start = page_num
                current_doc_is_mawb = True
            elif current_doc_start is None:
                # First page doesn't have MAWB marker - include it anyway
                current_doc_start = page_num
                current_doc_is_mawb = False

        # Close final document
        if current_doc_start is not None:
            max_page = max(page_texts.keys())
            documents.append(
                {
                    "start_page": current_doc_start,
                    "end_page": max_page,
                    "page_count": max_page - current_doc_start + 1,
                    "is_mawb_start": current_doc_is_mawb,
                    "awb_number": None,
                }
            )

        if len(documents) > 1:
            # Successfully found multiple documents using MAWB markers
            self._enrich_documents_with_awbs(documents, page_texts)
            documents = self._merge_same_awb_documents(documents)
            return documents

        # ===== STRATEGY 3: Fallback to AWB-based splitting (TERTIARY) =====
        documents = self._presplit_by_awb_as_markers(page_texts, mawb_starts)
        self._enrich_documents_with_awbs(documents, page_texts)
        documents = self._merge_same_awb_documents(documents)
        return documents

    def _enrich_documents_with_awbs(
        self, documents: List[Dict[str, any]], page_texts: Dict[int, str]
    ):
        """Extract AWB numbers for each document range (in-place modification)."""
        for doc in documents:
            doc["awb_number"] = self._extract_awb_number_from_document_block(doc, page_texts)

    def _merge_same_awb_documents(
        self, documents: List[Dict[str, any]]
    ) -> List[Dict[str, any]]:
        """
        Merge consecutive documents that share the same AWB number into one.

        When a multi-page attachment (e.g. a 3-page HKG Customs Manifest) follows
        an AWB form, the shipper/MAWB-marker splitter may create multiple split
        documents all pointing to the same AWB number.  Merging them into a single
        wide-range document prevents the extraction loop from processing and
        displaying the same AWB multiple times.

        Documents with awb_number=None are never merged with anything.
        """
        if not documents:
            return documents

        merged: List[Dict[str, any]] = []
        current = dict(documents[0])  # shallow copy

        for doc in documents[1:]:
            same_awb = (
                doc.get("awb_number")
                and current.get("awb_number")
                and doc["awb_number"] == current["awb_number"]
            )
            if same_awb:
                # Extend the current document's page range to include this one
                current["end_page"] = doc["end_page"]
                current["page_count"] = current["end_page"] - current["start_page"] + 1
            else:
                merged.append(current)
                current = dict(doc)

        merged.append(current)
        return merged

    def extract_document_by_range(
        self, raw_pdf: bytes, start_page: int, end_page: int, extractor
    ) -> str:
        """
        Extract text from a specific page range in the PDF.

        Args:
            raw_pdf: PDF bytes
            start_page: Starting page (1-indexed)
            end_page: Ending page (1-indexed, inclusive)
            extractor: PDFTextExtractor instance for this range

        Returns:
            Concatenated text from pages in range
        """
        page_texts = []

        for page_num, _total, text, _method in extractor.scan_pages(raw_pdf):
            if start_page <= page_num <= end_page:
                page_texts.append(text)
            elif page_num > end_page:
                break

        return "\n".join(page_texts)

    def presplit_pdf_with_text(
        self, raw_pdf: bytes, use_extractor: bool = True
    ) -> List[Dict[str, any]]:
        """
        Pre-split PDF and extract text for each document range.

        Args:
            raw_pdf: PDF bytes
            use_extractor: If True, use self.extractor for OCR

        Returns:
            List of dicts:
            {
                'start_page': int,
                'end_page': int,
                'awb_number': str or None,
                'text': str (extracted text for this range),
                'page_count': int,
            }
        """
        # Get page ranges
        ranges = self.presplit_pdf_into_ranges(raw_pdf, use_extractor=use_extractor)

        # Extract text for each range
        if use_extractor and self.extractor:
            for doc_range in ranges:
                text = self.extract_document_by_range(
                    raw_pdf,
                    doc_range["start_page"],
                    doc_range["end_page"],
                    self.extractor,
                )
                doc_range["text"] = text
        else:
            # Basic extraction
            with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
                for doc_range in ranges:
                    start_idx = doc_range["start_page"] - 1
                    end_idx = doc_range["end_page"]
                    pages = pdf.pages[start_idx:end_idx]
                    texts = [page.extract_text() or "" for page in pages]
                    doc_range["text"] = "\n".join(texts)

        return ranges

    # ------------------------------------------------------------------
    # Fast presplit for scanned PDFs
    # ------------------------------------------------------------------

    @staticmethod
    def _fast_ocr_page(page_num: int, img_arr, top_fraction: float = 0.20) -> tuple[int, str]:
        """
        OCR a pre-rendered numpy image array using settings optimised for boundary
        detection only (NOT full-quality extraction).

        NOTE: fitz/PyMuPDF objects are NOT thread-safe. The caller must render each
        page to a numpy array in the main thread BEFORE submitting to a thread pool.
        Only the Tesseract call (this function) runs in the worker thread.

        Settings:
        - 300 DPI render (caller's responsibility — high enough to reliably read
          AWB numbers like 233-10166763 even on poor-quality scans)
        - Top `top_fraction` of the image (default 20 %: AWB number + Shipper label
          are always in the top 12-15 % of an IATA AWB form; 20 % adds a safe margin)
        - OEM 1 (LSTM only, ~30 % faster than OEM 3)
        - No OSD / auto-rotation (saves ~0.5-1 s per page)
        - PSM 6 (uniform text block)

        Returns (page_num, text). Falls back to empty string if Tesseract unavailable.
        """
        try:
            import pytesseract as _tess
            from PIL import Image as _PILImage
        except ImportError:
            return page_num, ""

        try:
            # Crop to top fraction only
            crop_h = max(1, int(img_arr.shape[0] * top_fraction))
            cropped = img_arr[:crop_h, :, :]
            pil_img = _PILImage.fromarray(cropped)
            cfg = "--oem 1 --psm 6"
            text = _tess.image_to_string(pil_img, lang="eng", config=cfg)
            return page_num, text
        except Exception:
            return page_num, ""

    @staticmethod
    def _detect_rotation_page(page_num: int, img_arr) -> tuple[int, int]:
        """
        Detect page orientation using Tesseract OSD (--psm 0) on the full
        pre-rendered image.

        Returns (page_num, rotate_degrees) where rotate_degrees is the angle
        in degrees (0 / 90 / 180 / 270) needed to rotate the image
        counter-clockwise to make the content upright.
        Convention: Tesseract's `rotate` field = CCW degrees to correct.

        Falls back to (page_num, 0) if OSD is unavailable or fails (e.g. too
        few characters on the page for reliable detection).

        NOTE: Runs in a worker thread — img_arr must be a plain numpy array
        (no fitz objects).
        """
        try:
            import pytesseract as _tess
            from PIL import Image as _PILImage
            pil_img = _PILImage.fromarray(img_arr)
            osd = _tess.image_to_osd(
                pil_img,
                config="--psm 0 --oem 1",
                output_type=_tess.Output.DICT,
            )
            rotate = int(osd.get("rotate", 0))
            return page_num, rotate
        except Exception:
            return page_num, 0

    def presplit_pdf_fast(self, raw_pdf: bytes, max_workers: int = 4) -> List[Dict[str, any]]:
        """
        Fast presplit optimised for scanned PDFs.

        Key differences from the standard path:
        - 300 DPI rendering — high enough to reliably OCR small AWB number digits
          even on low-quality scans; 200 DPI still misses digits on poor originals.
        - OCR only the top 20 % of each page — the IATA AWB header (AWB number,
          "Shipper's Name and Address", "Not Negotiable…") always lives there.
        - OEM 1 / PSM 6 — LSTM only, no OSD rotation detection.
        - Parallel Tesseract: pixmaps are rendered sequentially in the main thread
          (PyMuPDF is NOT thread-safe), then OCR runs concurrently in a thread pool.

        Typical speedup vs normal mode: 3-5×  (small crop + parallelism).
        Accuracy for AWB number detection: better than normal mode on poor scans.

        Returns same structure as presplit_pdf_with_text() (includes 'text' key).
        """
        try:
            import fitz as _fitz
            import numpy as np
        except ImportError:
            # PyMuPDF not available — fall back to standard path
            return self.presplit_pdf_with_text(raw_pdf, use_extractor=bool(self.extractor))

        MIN_NATIVE_CHARS = 50
        DPI = 300  # 300 DPI needed to reliably OCR small AWB number digits on poor scans

        # ── Step 1: collect native text per page via pdfplumber ────────────
        page_texts: Dict[int, str] = {}
        pages_needing_ocr: list[int] = []

        with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                native = page.extract_text() or ""
                if len(native.strip()) >= MIN_NATIVE_CHARS:
                    page_texts[page_num] = native
                else:
                    page_texts[page_num] = ""  # placeholder
                    pages_needing_ocr.append(page_num)

        # ── Step 2: render all scanned pages to numpy IN MAIN THREAD ───────
        # PyMuPDF (fitz) is NOT thread-safe — never pass fitz objects to workers.
        # We render here and pass only plain numpy arrays to the thread pool.
        page_images: Dict[int, "np.ndarray"] = {}
        if pages_needing_ocr:
            fitz_doc = _fitz.open(stream=raw_pdf, filetype="pdf")
            mat = _fitz.Matrix(DPI / 72, DPI / 72)
            try:
                for page_num in pages_needing_ocr:
                    pix = fitz_doc.load_page(page_num - 1).get_pixmap(matrix=mat, alpha=False)
                    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width, 3
                    )
                    page_images[page_num] = arr
            finally:
                fitz_doc.close()

        # ── Step 3: parallel Tesseract OCR + OSD on pre-rendered images ───
        # OCR (top 20%, PSM 6) → text for boundary detection
        # OSD (full image, PSM 0) → per-page rotation correction angle
        page_rotations: Dict[int, int] = {}
        if page_images:
            ocr_futures: dict = {}
            osd_futures: dict = {}
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for page_num, img_arr in page_images.items():
                    ocr_futures[pool.submit(self._fast_ocr_page, page_num, img_arr, 0.20)] = page_num
                    osd_futures[pool.submit(self._detect_rotation_page, page_num, img_arr)] = page_num
                for future in as_completed(ocr_futures):
                    pn, text = future.result()
                    page_texts[pn] = text
                for future in as_completed(osd_futures):
                    pn, rotation = future.result()
                    if rotation != 0:
                        page_rotations[pn] = rotation

        # ── Step 3: run the standard splitting logic on collected texts ─────
        documents = self._presplit_by_shipper_marker(page_texts)
        if len(documents) <= 1:
            # Try MAWB marker fallback
            mawb_starts = {
                pn: self._find_mawb_start_in_page(txt)
                for pn, txt in page_texts.items()
            }
            docs2 = []
            current_start = None
            for page_num in sorted(page_texts.keys()):
                if mawb_starts[page_num]:
                    if current_start is not None:
                        docs2.append({
                            "start_page": current_start,
                            "end_page": page_num - 1,
                            "page_count": page_num - current_start,
                            "is_mawb_start": True,
                            "awb_number": None,
                        })
                    current_start = page_num
                elif current_start is None:
                    current_start = page_num
            if current_start is not None:
                max_page = max(page_texts.keys())
                docs2.append({
                    "start_page": current_start,
                    "end_page": max_page,
                    "page_count": max_page - current_start + 1,
                    "is_mawb_start": True,
                    "awb_number": None,
                })
            if len(docs2) > 1:
                documents = docs2
            else:
                documents = self._presplit_by_awb_as_markers(page_texts, {})

        self._enrich_documents_with_awbs(documents, page_texts)
        documents = self._merge_same_awb_documents(documents)

        # ── Step 5: attach page text and rotation map to each document ────
        for doc in documents:
            doc["text"] = "\n".join(
                page_texts.get(p, "")
                for p in range(doc["start_page"], doc["end_page"] + 1)
            )
            # Per-page rotation corrections (only scanned pages with non-zero rotation).
            # Key: 1-based page number. Value: CCW degrees to rotate to make content upright.
            # Pages not present in the dict require no rotation.
            doc["page_rotations"] = {
                p: page_rotations[p]
                for p in range(doc["start_page"], doc["end_page"] + 1)
                if p in page_rotations
            }

        return documents

