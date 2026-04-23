#!/usr/bin/env python3
"""
Fix: Extract ALL Master AWBs from PDF (not just first)
Pass AWB structure to LLM via prompt template
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()

# 1. Create AWB_STRUCTURE_PROMPT constant
prompt_module = '''"""
AWB Extraction Prompt Template
Describes the IATA AWB structure to LLM for better extraction
"""

AWB_STRUCTURE_PROMPT = """You are an expert Air Waybill (AWB) parser trained on IATA standards.

## IATA Air Waybill Structure:
- Master AWB: Document issued by shipper/freight forwarder
- Contains: Shipper, Consignee, Agent, Origin, Destination, Cargo details, Flight info
- Identified by: "Air Waybill", "Not negotiable", "Issued by"
- Format: AWB number has format XXX-YYYYYYYY (3-digit prefix, 8-digit serial)

## Field Locations (typical IATA form):
- **AWB NUMBER**: Top right, format 233-XXXXXXXX
- **SHIPPER**: Box 1, company name and address
- **CONSIGNEE**: Box 2, receiver company name and address  
- **AGENT**: Box 4, agent name (often same as shipper)
- **ORIGIN**: Airport of Departure (3-letter IATA code)
- **DESTINATION**: Airport of Destination (3-letter IATA code)
- **REQUESTED FLIGHT**: Flight number (e.g., CP137, MI200) and date
- **PIECES**: No. of Pieces (integer count)
- **WEIGHT**: Gross Weight in KG (decimal number, may use comma as decimal separator)
- **GOODS DESCRIPTION**: "Said to contain" or consolidation contents

## Key Rules:
1. AWB number MUST be in format XXX-YYYYYYYY
2. Airport codes MUST be 3 uppercase letters (IATA format)
3. Weight and Pieces are NUMBERS
4. Company names should NOT include "Air Waybill" or legal text
5. If field is missing or unclear, return null (not empty string)
6. For weights with comma (1148,4), convert to decimal (1148.4)

## OCR Challenges:
- Text may have OCR errors, garbled characters, special symbols
- Fields may be separated by lines, boxes, or form fields
- Accept variations in field labels (e.g., "Pieces", "PCS", "No. of Pcs")

Given the following OCR text, extract ONLY this JSON (no markdown, no explanations):
"""

def get_extraction_prompt(ocr_text: str) -> str:
    """Build full extraction prompt with OCR text"""
    return AWB_STRUCTURE_PROMPT + f"""

OCR TEXT FROM DOCUMENT:
{ocr_text}

Return ONLY this JSON structure (no other text):
{{
    "awb_number": "XXX-YYYYYYYY or null",
    "shipper": "Company name or null",
    "consignee": "Company name or null",
    "agent": "Agency name or null",
    "origin": "3-letter IATA code or null",
    "destination": "3-letter IATA code or null",
    "pieces": "Integer or null",
    "weight": "Number (decimal) or null",
    "flight_number": "Flight code like CP137 or null",
    "flight_date": "YYYY-MM-DD or null",
    "goods_description": "What is being shipped or null"
}}
"""
'''

prompt_path = PROJECT_ROOT / "app" / "interpretation" / "awb_extraction_prompt.py"
prompt_path.write_text(prompt_module, encoding='utf-8')
print("✅ Created awb_extraction_prompt.py with structured IATA AWB prompt")

# 2. Create a new multi-AWB splitter by "Not negotiable" markers
splitter_fix = '''"""
Extract ALL Master AWBs from PDF
Finds all "Not negotiable Air Waybill" sections
"""

import re
from typing import List, Dict
from app.interpretation.awb_number import AWB_RE, _fix_ocr_digits


def find_all_master_awb_sections(text: str) -> List[Dict[str, str]]:
    """
    Find ALL Master AWB sections in PDF text.
    Looks for "Not negotiable" markers and splits between them.
    
    Args:
        text: Full concatenated PDF text
    
    Returns:
        List of dicts with 'text' (section content) and 'start_pos', 'end_pos'
    """
    
    # Find all positions of Master AWB markers
    marker = "NOT NEGOTIABLE"
    master_positions = []
    
    for match in re.finditer(marker, text, re.IGNORECASE):
        master_positions.append(match.start())
    
    if not master_positions:
        # No Master AWB found
        return []
    
    # Extract sections between markers
    sections = []
    for i, pos in enumerate(master_positions):
        # Go back 1000 chars to capture start of section
        start = max(0, pos - 1000)
        
        # Go forward to next marker or end of text
        if i + 1 < len(master_positions):
            end = master_positions[i + 1]
        else:
            end = len(text)
        
        section_text = text[start:end].strip()
        
        # Verify this section has an AWB number
        awb_match = AWB_RE.search(section_text)
        if awb_match:
            sections.append({
                'text': section_text,
                'start_pos': start,
                'end_pos': end,
                'marker_pos': pos,
            })
    
    return sections
'''

splitter_multi_path = PROJECT_ROOT / "app" / "extraction" / "awb_multisplit.py"
splitter_multi_path.write_text(splitter_fix, encoding='utf-8')
print("✅ Created awb_multisplit.py for finding ALL Master AWBs")

# 3. Update the LLM extractor to use the structured prompt
llm_extractor_path = PROJECT_ROOT / "app" / "interpretation" / "awb_llm_extractor.py"
llm_extractor_code = llm_extractor_path.read_text(encoding='utf-8')

# Replace the extract method with one that uses the structured prompt
old_extract = """def extract(self, text: str) -> Dict[str, Any]:
        \"\"\"
        Extract AWB fields from OCR text using LLM.
        
        Args:
            text: OCR-extracted text from AWB document
        
        Returns:
            Dict with fields: awb_number, shipper, consignee, origin, destination,
                            pieces, weight, flight_number, flight_date, goods_description
        \"\"\"
        
        # Prompt for LLM
        prompt = f\"\"\"You are an expert in Air Waybill (AWB) document parsing.
Given the following OCR-extracted text from an Air Waybill, extract the key information and return it as JSON.

TEXT:
{text}

Extract EXACTLY these fields from the AWB. Return ONLY valid JSON (no markdown, no extra text):
{{
    "awb_number": "XXX-YYYYYYYY (3 digits prefix, 8 digits serial, e.g. 233-12345678)",
    "shipper": "Company name of shipper",
    "consignee": "Company name of consignee/receiver",
    "origin": "3-letter IATA airport code (e.g. MXP, FCO, HKG)",
    "destination": "3-letter IATA airport code",
    "pieces": "Integer number of pieces/packages",
    "weight": "Float number (total gross weight in kg)",
    "flight_number": "Flight number (e.g. CP137, MI200)",
    "flight_date": "Date in YYYY-MM-DD format",
    "goods_description": "What is being shipped"
}}

RULES:
- For missing fields, use null (not empty string)
- AWB number must be in format XXX-YYYYYYYY
- IATA codes must be 3 uppercase letters
- Weight must be a number
- Return ONLY the JSON object, nothing else
\"\"\"
        
        # Call LLM
        try:
            llm_response = self.llm.extract_awb_json(prompt)
            
            # Parse JSON response
            result = json.loads(llm_response)
            
            # Clean up the result
            return self._clean_extraction(result)
        except Exception as e:
            print(f"LLM extraction error: {e}")
            return self._empty_result()"""

new_extract = """def extract(self, text: str) -> Dict[str, Any]:
        \"\"\"
        Extract AWB fields from OCR text using LLM with structured prompt.
        
        Args:
            text: OCR-extracted text from AWB document
        
        Returns:
            Dict with fields: awb_number, shipper, consignee, origin, destination,
                            pieces, weight, flight_number, flight_date, goods_description
        \"\"\"
        from app.interpretation.awb_extraction_prompt import get_extraction_prompt
        
        # Build prompt with AWB structure guidance
        prompt = get_extraction_prompt(text)
        
        # Call LLM
        try:
            llm_response = self.llm.extract_awb_json(prompt)
            
            # Parse JSON response
            result = json.loads(llm_response)
            
            # Clean up the result
            return self._clean_extraction(result)
        except Exception as e:
            print(f"LLM extraction error: {e}")
            return self._empty_result()"""

llm_extractor_code = llm_extractor_code.replace(old_extract, new_extract)
llm_extractor_path.write_text(llm_extractor_code, encoding='utf-8')
print("✅ Updated awb_llm_extractor.py to use structured prompt")

# 4. Update pdf_upload.py to extract ALL Master AWBs
pdf_upload_path = PROJECT_ROOT / "app" / "ui" / "pages" / "pdf_upload.py"
pdf_code = pdf_upload_path.read_text(encoding='utf-8')

old_run_extraction = """if run_extraction:
        try:
            with st.spinner("Extracting Master AWB using AI..."):
                # Import LLM extractor
                from app.interpretation.awb_llm_extractor import AwbLlmExtractor
                from app.extraction.awb_document_splitter import AwbDocumentSplitter
                import re
                
                # STEP 1: Find Master AWB section (first page with "Not negotiable" or "233-")
                master_marker_pos = text.upper().find("NOT NEGOTIABLE AIR WAYBILL")
                first_233_pos = text.find("233-")
                
                if master_marker_pos == -1 and first_233_pos == -1:
                    st.error("No Master AWB found in PDF (no '233-' pattern and no 'Not negotiable' marker)")
                    return
                
                # Determine where to start extracting
                if master_marker_pos != -1:
                    start_pos = max(0, master_marker_pos - 2000)
                else:
                    start_pos = max(0, first_233_pos - 1000)
                
                # Extract roughly one page
                end_pos = start_pos + 5000
                page_text = text[start_pos:end_pos]
                
                st.session_state["master_page_text"] = page_text
                
                # STEP 2: Use LLM to extract fields from OCR text
                llm_provider = get_llm()
                llm_extractor = AwbLlmExtractor(llm_provider=llm_provider)
                
                # Try to extract with LLM
                extracted_dict = llm_extractor.extract(page_text)
                
                if not extracted_dict.get("awb_number"):
                    st.error("LLM could not extract AWB number from document")
                    st.write("Extracted data:", extracted_dict)
                    return
                
                # STEP 3: Store result
                st.session_state["awb_results"] = {
                    'document_text': page_text,
                    'extracted_data': extracted_dict,
                    'llm_used': True,
                }
                
                st.success(f"✅ Extracted Master AWB {extracted_dict.get('awb_number')}")
                st.json(extracted_dict)"""

new_run_extraction = """if run_extraction:
        try:
            with st.spinner("Extracting ALL Master AWBs using AI..."):
                # Import extractors
                from app.interpretation.awb_llm_extractor import AwbLlmExtractor
                from app.extraction.awb_multisplit import find_all_master_awb_sections
                
                # STEP 1: Find ALL Master AWB sections in PDF
                awb_sections = find_all_master_awb_sections(text)
                
                if not awb_sections:
                    st.error("No Master AWBs found in PDF (looking for 'Not negotiable' marker)")
                    return
                
                st.info(f"Found {len(awb_sections)} Master AWB section(s)")
                
                # STEP 2: Use LLM to extract from each section
                llm_provider = get_llm()
                llm_extractor = AwbLlmExtractor(llm_provider=llm_provider)
                
                extracted_awbs = []
                for i, section in enumerate(awb_sections):
                    with st.spinner(f"Processing Master AWB {i+1}/{len(awb_sections)}..."):
                        extracted = llm_extractor.extract(section['text'])
                        
                        if extracted.get("awb_number"):
                            extracted_awbs.append(extracted)
                            st.success(f"✅ Extracted: {extracted.get('awb_number')}")
                        else:
                            st.warning(f"⚠️ Could not extract AWB #{i+1}")
                
                if not extracted_awbs:
                    st.error("LLM could not extract any AWB from the document")
                    return
                
                # STEP 3: Store results
                st.session_state["awb_results"] = {
                    'sections': awb_sections,
                    'extracted_awbs': extracted_awbs,
                    'llm_used': True,
                }
                
                st.success(f"✅ Successfully extracted {len(extracted_awbs)} Master AWB(s)")"""

pdf_code = pdf_code.replace(old_run_extraction, new_run_extraction)

# Update the display section
old_display = """# Get extracted AWB from LLM
            extracted_dict = st.session_state["awb_results"].get("extracted_data", {})
            
            # Convert dict to list for consistency
            normalized_awbs = [extracted_dict] if extracted_dict.get("awb_number") else []"""

new_display = """# Get all extracted AWBs from LLM
            extracted_awbs = st.session_state["awb_results"].get("extracted_awbs", [])
            normalized_awbs = extracted_awbs if extracted_awbs else []"""

pdf_code = pdf_code.replace(old_display, new_display)

pdf_upload_path.write_text(pdf_code, encoding='utf-8')
print("✅ Updated pdf_upload.py to extract ALL Master AWBs with structured prompts")

print("\n" + "=" * 70)
print("SUCCESS! Multi-Master AWB + Structured Prompt")
print("=" * 70)
print("\nChanges:")
print("  ✓ Finds ALL 'Not negotiable' markers in PDF")
print("  ✓ Extracts each Master AWB separately")
print("  ✓ Passes IATA AWB structure to LLM in prompt")
print("  ✓ LLM understands field locations and formats")
print("\nNow the flow is:")
print("  1. Find all Master AWB sections (by 'Not negotiable')")
print("  2. For each section, invoke LLM with structured prompt")
print("  3. LLM knows IATA form structure, extracts fields correctly")
print("\nRestart Streamlit:")
print("  streamlit run app/ui/web_streamlit.py")