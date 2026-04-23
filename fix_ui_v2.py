#!/usr/bin/env python3
"""Update pdf_upload.py with:
1. Filter for AWB prefix 233 only
2. Add LLM refine section for each AWB (before iCargo fetch)
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
pdf_upload_path = PROJECT_ROOT / "app" / "ui" / "pages" / "pdf_upload.py"

print("Updating pdf_upload.py with 233 filter and per-AWB LLM...")

# Read the current file
current_code = pdf_upload_path.read_text(encoding='utf-8')

# Find where to split - right before the section that displays AWBs
split_point = current_code.find("normalized_awbs = st.session_state[\"awb_results\"][\"normalized\"]")

if split_point == -1:
    print("ERROR: Could not find expected section in pdf_upload.py")
    exit(1)

# Keep everything before
before_section = current_code[:split_point]

# New section with 233 filter and per-AWB LLM
new_section = '''normalized_awbs = st.session_state["awb_results"]["normalized"]
    
    # FILTER: Keep only AWB with prefix 233
    filtered_awbs = [awb for awb in normalized_awbs if awb.awb_prefix == "233"]
    
    if not filtered_awbs:
        st.warning(f"No AWBs with prefix 233 found. (Total extracted: {len(normalized_awbs)})")
        return
    
    st.subheader(f"Extracted AWBs with prefix 233 ({len(filtered_awbs)})")

    # Summary table with expandable rows
    for idx, awb in enumerate(filtered_awbs):
        with st.expander(
            f"📦 {awb.awb_number or 'N/A'} | {awb.shipper or 'Unknown'} -> {awb.consignee or 'N/A'} | {awb.pieces}x {awb.weight}kg",
            expanded=(idx == 0)
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
            
            # ---------- LLM REFINE SECTION ----------
            st.divider()
            st.write("**🤖 Refine with LLM (Optional)**")
            st.caption("Apply Hybrid Extraction to improve data accuracy using AI")
            
            llm_display = get_llm_display_name()
            
            col_llm1, col_llm2 = st.columns([1, 1])
            with col_llm1:
                run_llm_for_awb = st.button(
                    f"Apply LLM ({llm_display})",
                    key=f"llm_refine_{idx}"
                )
            with col_llm2:
                reload_llm_btn = st.button(f"🔄 Reload {llm_display}", key=f"reload_llm_{idx}")
            
            if reload_llm_btn:
                clear_llm_cache()
                st.info("LLM cache cleared. Refresh to reload model.")
            
            if run_llm_for_awb:
                try:
                    with st.spinner(f"Applying LLM to {awb.awb_number}..."):
                        from app.extraction.awb_document_splitter import AwbDocumentSplitter
                        
                        # Get the original text for this AWB
                        doc_texts = [doc['text'] for doc in st.session_state["awb_results"]["documents"]]
                        llm_provider = get_llm()
                        
                        # Apply hybrid extraction to this AWB's text
                        hybrid = AwbHybridExtractor(llm_provider=llm_provider)
                        improved_data = hybrid.extract(doc_texts[idx])
                        
                        # Store improved data in session
                        if "llm_refined_awbs" not in st.session_state:
                            st.session_state["llm_refined_awbs"] = {}
                        st.session_state["llm_refined_awbs"][awb.awb_number] = improved_data
                        
                        st.success(f"LLM applied to {awb.awb_number}")
                        st.write("**Improved data:**")
                        st.json(improved_data)
                except Exception as e:
                    st.error(f"LLM failed: {e}")
            
            # ---------- DOWNLOAD SINGLE AWB ----------
            st.divider()
            st.write("**⬇️ Download**")
            
            # Use LLM refined data if available, otherwise original AWB
            display_awb = st.session_state.get("llm_refined_awbs", {}).get(awb.awb_number, awb.dict())
            awb_json = json.dumps(display_awb, indent=2, default=str)
            
            st.download_button(
                label=f"Download {awb.awb_number} (JSON)",
                data=awb_json,
                file_name=f"awb_{awb.awb_number}.json",
                mime="application/json",
                key=f"dl_single_{idx}"
            )
            
            # ---------- iCARGO COMPARISON ----------
            st.divider()
            st.write("**📊 Compare with iCargo**")
            
            fetch_for_this = st.button(
                f"Fetch & Compare with iCargo",
                key=f"fetch_icargo_{idx}"
            )
            
            if fetch_for_this:
                if awb.awb_prefix and awb.awb_serial:
                    try:
                        with st.spinner(f"Fetching {awb.awb_number} from iCargo..."):
                            ic = ICargoIBSClient()
                            icargo_result = ic.get_awb(awb.awb_number)
                            
                            # Use refined AWB data if available
                            if awb.awb_number in st.session_state.get("llm_refined_awbs", {}):
                                extracted_flat = st.session_state["llm_refined_awbs"][awb.awb_number]
                            else:
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
    
    # All AWBs as JSON (use LLM refined if available)
    batch_data = []
    for awb in filtered_awbs:
        if awb.awb_number in st.session_state.get("llm_refined_awbs", {}):
            batch_data.append(st.session_state["llm_refined_awbs"][awb.awb_number])
        else:
            batch_data.append(awb.dict())
    
    all_awbs_json = json.dumps(batch_data, indent=2, default=str)
    st.download_button(
        label="⬇️ Download All (JSON)",
        data=all_awbs_json,
        file_name=f"awbs_batch_{len(filtered_awbs)}.json",
        mime="application/json"
    )
    
    # All AWBs as CSV
    try:
        import pandas as pd
        df = pd.DataFrame(batch_data)
        csv_data = df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download All (CSV)",
            data=csv_data,
            file_name=f"awbs_batch_{len(filtered_awbs)}.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.warning(f"CSV export not available: {e}")
'''

# Find where the old "Batch Download" section starts and cut it
batch_dl_start = new_section.find("# ---------- Batch Download ----------")
old_batch_start = current_code.find("# ---------- Batch Download ----------", split_point)

if old_batch_start == -1:
    # If old batch section not found, just append at end
    new_code = before_section + new_section + "\n"
else:
    # Keep rest after old batch section
    rest_after = current_code[old_batch_start:]
    new_code = before_section + new_section

# Write back
pdf_upload_path.write_text(new_code, encoding='utf-8')

print("✅ SUCCESS! pdf_upload.py updated:")
print("  ✓ Filter: Only AWB with prefix 233")
print("  ✓ Per-AWB section: LLM refine (before iCargo)")
print("  ✓ Per-AWB comparison: iCargo fetch & diff")
print("  ✓ Batch download: JSON + CSV (with LLM refinements)")
print("\nNext: Restart Streamlit")