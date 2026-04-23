"""
Extract ALL Master AWBs from PDF
Finds all "Not negotiable Air Waybill" sections
"""

import re
from typing import List, Dict
from app.interpretation.awb_number import AWB_RE, _fix_ocr_digits


def find_all_master_awb_sections(text: str) -> List[Dict[str, str]]:
    """
    Find ALL Master AWB sections in PDF text.
    
    Specific criteria to identify AWB (and exclude HAWB and other documents):
    Three key indicators that MUST all appear (in ANY order, anywhere within a section):
    1. "Not negotiable" marker
    2. "Air Waybill" text
    3. "Issued by" text (indicates Master AWB with issuing airline/agent)
    
    Uses a larger context window to account for OCR document layout.
    
    Args:
        text: Full concatenated PDF text
    
    Returns:
        List of dicts with 'text' (section content) and 'start_pos', 'end_pos'
    """
    
    # Find all positions of "NOT NEGOTIABLE" markers
    marker = "NOT NEGOTIABLE"
    marker_positions = []
    
    for match in re.finditer(marker, text, re.IGNORECASE):
        marker_positions.append(match.start())
    
    if not marker_positions:
        # No "Not negotiable" markers found
        return []
    
    # Extract sections, filtering by AWB-specific criteria
    sections = []
    large_context_window = 5000  # chars to look around each marker for validation
    
    for marker_idx, marker_pos in enumerate(marker_positions):
        # Define large context window around this marker for validation
        context_start = max(0, marker_pos - large_context_window)
        context_end = min(len(text), marker_pos + large_context_window)
        context = text[context_start:context_end].upper()
        
        # Check if this is a real AWB (not HAWB or other doc type)
        # All THREE indicators must be present
        has_air_waybill = "AIR WAYBILL" in context
        # Accept both "ISSUED BY" and "ISSUING" (OCR sometimes garbles "Issued by" into "sudty" etc.)
        # "ISSUING CARRIER" appears elsewhere on the form and is reliable
        has_issued_by = "ISSUED BY" in context or "ISSUING" in context
        has_not_negotiable = "NOT NEGOTIABLE" in context
        
        if not (has_air_waybill and has_issued_by and has_not_negotiable):
            # Not a real AWB - skip this marker
            continue
        
        # This is an AWB! Now extract the full section
        # Go back to previous marker (to avoid including prior sections) or 2000 chars for first section
        if marker_idx > 0:
            section_start = marker_positions[marker_idx - 1]
        else:
            section_start = max(0, marker_pos - 2000)
        
        # Go forward to next marker or end of text
        if marker_idx + 1 < len(marker_positions):
            section_end = marker_positions[marker_idx + 1]
        else:
            section_end = len(text)
        
        section_text = text[section_start:section_end].strip()
        
        # Extract AWB number: search FORWARD first (from marker onwards).
        # CRITICAL: The previous section's AWB number appears in its footer, just before
        # this section's header. A backward search would capture that wrong number.
        # Forward search (from marker position) skips the contaminated footer area entirely.
        def _extract_awb_from_span(span_text):
            for m in AWB_RE.finditer(span_text):
                p = _fix_ocr_digits(m.group(1))
                n = _fix_ocr_digits(m.group(2)).replace(" ", "").replace("-", "")
                if p.isdigit() and n.isdigit():
                    return f"{p}-{n}"
            return None

        # 1st attempt: forward window (current form body + bottom footer + attached manifest)
        fwd_end = min(len(text), marker_pos + 5000)
        local_awb_number = _extract_awb_from_span(text[marker_pos:fwd_end])

        # 2nd attempt: small backward window (AWB header line is close before the marker)
        if not local_awb_number:
            bwd_start = max(0, marker_pos - 300)
            local_awb_number = _extract_awb_from_span(text[bwd_start:marker_pos])

        # 3rd attempt: full section (last resort)
        if not local_awb_number:
            local_awb_number = _extract_awb_from_span(section_text)
        
        if local_awb_number:
            sections.append({
                'text': section_text,
                'start_pos': section_start,
                'end_pos': section_end,
                'marker_pos': marker_pos,
                'awb_number': local_awb_number,  # Pre-extracted near marker (authoritative)
            })
    
    return sections


def analyse_awb_markers(text: str) -> list:
    """
    Debug function: returns analysis of every "NOT NEGOTIABLE" marker found,
    including which criteria passed/failed and why a marker was accepted or skipped.
    
    Returns:
        List of dicts with keys:
          - marker_pos: int
          - context_snippet: str (first 200 chars of context)
          - has_air_waybill: bool
          - has_issued_by: bool
          - has_not_negotiable: bool
          - is_valid_awb: bool (all 3 criteria)
          - awb_number_found: str or None
          - reason_skipped: str or None
    """
    marker = "NOT NEGOTIABLE"
    marker_positions = [m.start() for m in re.finditer(marker, text, re.IGNORECASE)]
    large_context_window = 5000

    analysis = []
    for marker_idx, marker_pos in enumerate(marker_positions):
        context_start = max(0, marker_pos - large_context_window)
        context_end = min(len(text), marker_pos + large_context_window)
        context = text[context_start:context_end].upper()

        has_air_waybill = "AIR WAYBILL" in context
        has_issued_by = "ISSUED BY" in context or "ISSUING" in context
        has_not_negotiable = "NOT NEGOTIABLE" in context
        is_valid = has_air_waybill and has_issued_by and has_not_negotiable

        # Determine section boundaries (same logic as find_all_master_awb_sections)
        if marker_idx > 0:
            section_start = marker_positions[marker_idx - 1]
        else:
            section_start = max(0, marker_pos - 2000)
        if marker_idx + 1 < len(marker_positions):
            section_end = marker_positions[marker_idx + 1]
        else:
            section_end = len(text)

        section_text = text[section_start:section_end]
        awb_match = AWB_RE.search(section_text)
        awb_found = None
        if awb_match:
            from app.interpretation.awb_number import _fix_ocr_digits
            p = _fix_ocr_digits(awb_match.group(1))
            n = _fix_ocr_digits(awb_match.group(2)).replace(" ", "").replace("-", "")
            if p.isdigit() and n.isdigit():
                awb_found = f"{p}-{n}"

        reason = None
        if not is_valid:
            missing = []
            if not has_air_waybill:
                missing.append("AIR WAYBILL")
            if not has_issued_by:
                missing.append("ISSUED BY")
            reason = f"Missing: {', '.join(missing)}"
        elif not awb_found:
            reason = "No AWB number pattern found in section"

        analysis.append({
            'marker_pos': marker_pos,
            'marker_idx': marker_idx,
            'context_snippet': text[marker_pos:marker_pos + 150].replace('\n', ' '),
            'has_air_waybill': has_air_waybill,
            'has_issued_by': has_issued_by,
            'has_not_negotiable': has_not_negotiable,
            'is_valid_awb': is_valid,
            'awb_number_found': awb_found,
            'accepted': is_valid and awb_found is not None,
            'reason_skipped': reason,
        })

    return analysis
