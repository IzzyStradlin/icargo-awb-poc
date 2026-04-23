#!/usr/bin/env python3
"""Fix pdf_upload.py to show multi-AWB extraction in Streamlit"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
pdf_upload_path = PROJECT_ROOT / "app" / "ui" / "pages" / "pdf_upload.py"

print("Updating pdf_upload.py for multi-AWB UI...")

# Read the current file
current_code = pdf_upload_path.read_text(encoding='utf-8')

# Find and replace the render_pdf_upload function
# We'll replace everything after the ICargoIBSClient class definition

# Find where to split
split_point = current_code.find("def render_pdf_upload(on_back):")

if split_point == -1:
    print("ERROR: Could not find render_pdf_upload function")
    exit(1)

# Keep everything before render_pdf_upload
before_function = current_code[:split_point]

# New render_pdf_upload function
new_render_function = '''def render_pdf_upload(on_back):
    st.title("📄 Upload PDF")

    if st.button("⬅️ Back"):
        on_back()
        st.stop()

    # Init session state
    defaults = {
        "pdf_hash": None,
        "extracted_text": None,
        "used_ocr": False,
        "awb_results": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    uploaded = st.file_uploader("Select a PDF", type=["pdf"])
    if not uploaded:
        st.info("Load a PDF to start.")
        return

    raw_pdf = uploaded.read()

    # ---------- OCR options ----------
    with st.expander("Text Extraction / OCR Options", expanded=False):
        force_ocr = st.checkbox("Force OCR (even if PDF contains text)", value=False)
        min_chars = st.slider("Minimum character threshold to avoid OCR fallback", 0, 2000, 200, 50)
        ocr_lang = st.text_input("OCR Languages (Tesseract)", value="eng")
        ocr_dpi = st.selectbox("OCR DPI (quality vs speed)", [150, 200, 300], index=1)
        max_pages = st.number_input("Max pages (0 = all)", min_value=0, value=0, step=1)

    # ---------- detect PDF changes ----------
    pdf_hash = str(hash(raw_pdf))
    
    if st.session_state.pdf_hash != pdf_hash:
        st.session_state.pdf_hash = pdf_hash
        st.session_state.extracted_text = None
        st.session_state.used_ocr = False
        st.session_state.awb_results = None

    # ---------- extract text (cached in session) ----------
    if st.session_state.extracted_text is None:
        options = ExtractOptions(
            force_ocr=force_ocr,
            min_text_chars=min_chars,
            ocr_lang=ocr_lang.strip() or "eng",
            ocr_dpi=int(ocr_dpi),
            max_pages=None if int(max_pages) == 0 else int(max_pages),
        )
        extractor = PDFTextExtractor(options=options)
        with st.spinner("Extracting text..."):
            text, used_ocr = extractor.extract_text(raw_pdf)
        st.session_state.extracted_text = text
        st.session_state.used_ocr = used_ocr

    text = st.session_state.extracted_text
    used_ocr = st.session_state.used_ocr

    st.success(f"Loaded: {uploaded.name} ({uploaded.size} bytes)")
    st.caption("OCR used: ✅" if used_ocr else "OCR used: ❌")

    st.subheader("1) Extracted Text")
    st.text_area("Text Output", value=text, height=250)

    st.divider()

    # ---------- Multi-AWB Extraction ----------
    st.subheader("2) Multi-AWB Extraction")

    col1, col2 = st.columns([1, 1])
    with col1:
        run_extraction = st.button("🚀 Extract All AWBs")
    with col2:
        clear_extraction = st.button("Reset Extraction")

    if clear_extraction:
        st.session_state["awb_results"] = None

    if run_extraction:
        try:
            with st.spinner("Splitting PDF and extracting AWBs..."):
                # Import here to avoid circular dependencies
                from app.extraction.awb_document_splitter import AwbDocumentSplitter
                from app.interpretation.awb_field_detector import AwbFieldDetector
                from app.interpretation.awb_normalizer import AwbNormalizer
                
                # Split text into individual AWB documents
                splitter = AwbDocumentSplitter()
                documents = splitter.split_pdf_into_awb_documents(text)
                
                # Extract fields for each document
                doc_texts = [doc['text'] for doc in documents]
                detector = AwbFieldDetector()
                extraction_results = detector.extract_all(doc_texts)
                
                # Normalize
                normalizer = AwbNormalizer()
                normalized_awbs = [
                    normalizer.normalize(result.data) 
                    for result in extraction_results
                ]
                
                st.session_state["awb_results"] = {
                    'documents': documents,
                    'extraction_results': extraction_results,
                    'normalized': normalized_awbs,
                }
                st.success(f"✅ Extracted {len(normalized_awbs)} AWB(s)")
        except Exception as e:
            st.error(f"Extraction failed: {e}")
            import traceback
            traceback.print_exc()

    # ---------- Display extracted AWBs in expandable table ----------
    if st.session_state.get("awb_results") is None:
        st.info("Click 'Extract All AWBs' to begin.")
        return

    normalized_awbs = st.session_state["awb_results"]["normalized"]
    st.subheader(f"Extracted AWBs ({len(normalized_awbs)})")

    # Summary table with expandable rows
    for idx, awb in enumerate(normalized_awbs):
        with st.expander(
            f"📦 {awb.awb_number or 'N/A'} | {awb.shipper or 'Unknown'} → {awb.consignee or 'N/A'} | {awb.pieces}x {awb.weight}kg",
            expanded=(idx == 0)  # First one expanded by default
        ):
            col1, col2, col3 = st.columns([1, 1, 1])
            
            with col1:
                st.write("**Basic Info**")
                st.write(f"AWB: {awb.awb_number}")
                st.write(f"Shipper: {awb.shipper}")
                st.write(f"Consignee: {awb.consignee}")
                st.write(f"Agent: {awb.agent}")
            
            with col2:
                st.write("**Routing & Cargo**")
                st.write(f"Origin: {awb.origin}")
                st.write(f"Destination: {awb.destination}")
                st.write(f"Pieces: {awb.pieces}")
                st.write(f"Weight: {awb.weight}")
            
            with col3:
                st.write("**Flight Info**")
                st.write(f"Flight: {awb.flight_no}")
                st.write(f"Date: {awb.flight_date}")
                st.write(f"Goods: {awb.goods_description}")
            
            # Download single AWB
            awb_json = json.dumps(awb.dict(), indent=2, default=str)
            st.download_button(
                label=f"⬇️ Download {awb.awb_number}",
                data=awb_json,
                file_name=f"awb_{awb.awb_number}.json",
                mime="application/json",
                key=f"dl_single_{idx}"
            )
            
            # Diff with iCargo
            with st.expander("📊 Compare with iCargo", expanded=False):
                fetch_for_this = st.button(
                    f"Fetch iCargo for {awb.awb_number}",
                    key=f"fetch_icargo_{idx}"
                )
                
                if fetch_for_this:
                    if awb.awb_prefix and awb.awb_serial:
                        try:
                            with st.spinner(f"Fetching {awb.awb_number} from iCargo..."):
                                ic = ICargoIBSClient()
                                icargo_result = ic.get_awb(awb.awb_number)
                                
                                # Show diff
                                extracted_flat = awb.dict()
                                icargo_flat = map_icargo_awb_ibs(icargo_result)
                                rows = diff_awb(extracted_flat, icargo_flat)
                                
                                st.dataframe(rows, width='stretch')
                                
                                mism = [r for r in rows if not r["match"]]
                                if not mism:
                                    st.success("✅ No differences!")
                                else:
                                    st.warning(f"⚠️ {len(mism)} difference(s)")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("Invalid AWB number (missing prefix/serial)")

    # ---------- Batch Download ----------
    st.divider()
    st.subheader("📥 Batch Download")
    
    # All AWBs as JSON
    all_awbs_json = json.dumps(
        [awb.dict() for awb in normalized_awbs],
        indent=2,
        default=str
    )
    st.download_button(
        label="⬇️ Download All AWBs (JSON)",
        data=all_awbs_json,
        file_name=f"awbs_batch_{len(normalized_awbs)}.json",
        mime="application/json"
    )
    
    # All AWBs as CSV
    try:
        import pandas as pd
        df = pd.DataFrame([awb.dict() for awb in normalized_awbs])
        csv_data = df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download All AWBs (CSV)",
            data=csv_data,
            file_name=f"awbs_batch_{len(normalized_awbs)}.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.warning(f"CSV export not available: {e}")
'''

# Combine
new_code = before_function + new_render_function

# Write back
pdf_upload_path.write_text(new_code, encoding='utf-8')

print("✅ SUCCESS! pdf_upload.py updated with multi-AWB UI")
print("\nChanges:")
print("  - Replaced render_pdf_upload() with multi-AWB extraction")
print("  - Added expandable table view for all AWBs")
print("  - Added per-AWB iCargo comparison")
print("  - Added batch download (JSON + CSV)")
print("\nNext step: Restart Streamlit and upload a multi-AWB PDF")