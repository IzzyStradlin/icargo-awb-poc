# app/ui/pages/pdf_upload.py
"""
PDF → Claude Vision → AWB extraction.
Flow: upload PDF → auto-split by MAWB → Claude Vision per document → results.
No OCR step exposed to user. No Cohere. No regex parsing.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv

from app.extraction.pdf_text_extractor import PDFTextExtractor
from app.extraction.awb_document_presplitter import AwbDocumentPreSplitter
from app.interpretation.awb_vision_extractor import AwbVisionExtractor
from app.compare.awb_diff_ibs import map_icargo_awb_ibs, diff_awb
from app.ui.assets.branding import get_colors, get_brand_info

load_dotenv()


# ── Cached Vision extractor ────────────────────────────────────────────────
@st.cache_resource
def get_claude_vision() -> AwbVisionExtractor:
    return AwbVisionExtractor()


# ── iCargo IBS client ──────────────────────────────────────────────────────
class ICargoIBSClient:
    def __init__(self):
        self.base_url = (os.getenv("ICARGO_BASE_URL") or "https://mac-stag-icargo.ibsplc.aero").rstrip("/")
        self.username = os.getenv("ICARGO_USERNAME")
        self.password = os.getenv("ICARGO_PASSWORD")
        self.timeout = float(os.getenv("ICARGO_TIMEOUT", "15"))
        self.token = None
        if not self.username or not self.password:
            raise RuntimeError("ICARGO_USERNAME / ICARGO_PASSWORD missing in .env")

    def authenticate(self):
        url = f"{self.base_url}/auth/m4/private/v1/authenticate"
        r = requests.post(
            url,
            json={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Auth error: {r.status_code} {r.text}")
        self.token = r.json()["body"]["security"]["id_token"]

    def _headers(self):
        if not self.token:
            self.authenticate()
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def get_awb(self, awb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{awb_code}"
        r = requests.get(url, headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Error GET AWB: {r.status_code} {r.text}")
        return r.json()


# ── AWB form renderer ──────────────────────────────────────────────────────
def _val(v, suffix="") -> str:
    return f"{v}{suffix}" if v not in (None, "", "null") else "—"


def _fmt_addr(data: dict, prefix: str) -> str:
    parts = [
        data.get(f"{prefix}_street"),
        data.get(f"{prefix}_city"),
        data.get(f"{prefix}_province"),
        data.get(f"{prefix}_zip"),
        data.get(f"{prefix}_country"),
    ]
    return ", ".join(p for p in parts if p) or "—"


def _awb_form(awb_num: str, data: dict):
    """Render AWB fields in a grid mirroring the real AWB layout."""
    # Shipper | Consignee
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**Shipper**")
            st.markdown(f"**{_val(data.get('shipper'))}**")
            st.caption(_fmt_addr(data, "shipper"))
    with c2:
        with st.container(border=True):
            st.markdown("**Consignee**")
            st.markdown(f"**{_val(data.get('consignee'))}**")
            st.caption(_fmt_addr(data, "consignee"))

    # Agent | Routing
    c3, c4 = st.columns(2)
    with c3:
        with st.container(border=True):
            st.markdown("**Issuing Carrier's Agent**")
            st.markdown(f"**{_val(data.get('agent'))}**")
            st.caption(_fmt_addr(data, "agent"))
    with c4:
        with st.container(border=True):
            st.markdown("**AWB / Routing**")
            st.write(f"🔖 AWB: `{awb_num}`")
            st.write(f"✈️ {_val(data.get('origin'))} → {_val(data.get('destination'))}")
            st.write(f"🛫 Flight: **{_val(data.get('flight_number'))}**")
            st.write(f"📅 Date: **{_val(data.get('flight_date'))}**")

    # Cargo figures
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        with st.container(border=True):
            st.markdown("**Pcs (RCP)**")
            st.markdown(f"### {_val(data.get('pieces'))}")
    with c6:
        with st.container(border=True):
            st.markdown("**Gross Weight**")
            st.markdown(f"### {_val(data.get('weight'), ' kg')}")
    with c7:
        with st.container(border=True):
            st.markdown("**Chargeable Wt**")
            st.markdown(f"### {_val(data.get('chargeable_weight'), ' kg')}")
    with c8:
        with st.container(border=True):
            st.markdown("**Rate / Total**")
            st.write(f"Rate: **{_val(data.get('rate'))}**")
            st.write(f"Total: **{_val(data.get('total_charge'))}**")

    # Goods description
    with st.container(border=True):
        st.markdown("**Nature and Quantity of Goods**")
        st.text(data.get("goods_description") or "—")


def _hawb_form(hawb_num: str, data: dict):
    """Render House AWB fields."""
    # Shipper | Consignee
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**Shipper**")
            st.markdown(f"**{_val(data.get('shipper'))}**")
            st.caption(_fmt_addr(data, "shipper"))
    with c2:
        with st.container(border=True):
            st.markdown("**Consignee**")
            st.markdown(f"**{_val(data.get('consignee'))}**")
            st.caption(_fmt_addr(data, "consignee"))

    # Notify party (HAWB-specific)
    notify = data.get("notify_party")
    if notify and notify not in ("null", ""):
        with st.container(border=True):
            st.markdown("**Notify Party**")
            st.text(notify)

    # Routing
    with st.container(border=True):
        st.markdown("**Routing**")
        ca, cb, cc, cd = st.columns(4)
        ca.metric("Origin", _val(data.get("origin")))
        cb.metric("Destination", _val(data.get("destination")))
        cc.metric("Flight", _val(data.get("flight_number")))
        cd.metric("Date", _val(data.get("flight_date")))

    # Cargo figures
    c3, c4, c5, c6, c7 = st.columns(5)
    with c3:
        with st.container(border=True):
            st.markdown("**Pcs**")
            st.markdown(f"### {_val(data.get('pieces'))}")
    with c4:
        with st.container(border=True):
            st.markdown("**Gross Wt**")
            st.markdown(f"### {_val(data.get('weight'), ' kg')}")
    with c5:
        with st.container(border=True):
            st.markdown("**Chg Wt**")
            st.markdown(f"### {_val(data.get('chargeable_weight'), ' kg')}")
    with c6:
        with st.container(border=True):
            st.markdown("**Volume**")
            st.markdown(f"### {_val(data.get('volume'), ' m³')}")
    with c7:
        with st.container(border=True):
            st.markdown("**Total Charge**")
            st.markdown(f"### {_val(data.get('total_charge'))}")

    # Commodity details
    cd1, cd2 = st.columns(2)
    with cd1:
        with st.container(border=True):
            st.markdown("**HS Code**")
            st.code(data.get("hs_code") or "—")
    with cd2:
        with st.container(border=True):
            st.markdown("**Special Handling**")
            sh = data.get("special_handling")
            st.code(sh if sh and sh != "null" else "—")

    # Goods description
    with st.container(border=True):
        st.markdown("**Description of Goods**")
        st.text(data.get("goods_description") or "—")

    # Declared values
    dv1, dv2, dv3 = st.columns(3)
    dv1.metric("Dimensions", _val(data.get("dimensions")))
    dv2.metric("Decl. Value Carriage", _val(data.get("declared_value_carriage")))
    dv3.metric("Decl. Value Customs", _val(data.get("declared_value_customs")))


# ── Presplit helper ───────────────────────────────────────────────────────
def _split_pdf(raw_pdf: bytes, fast: bool = False) -> list[dict]:
    """
    Split the PDF into one document per MAWB.
    fast=True  → parallel low-DPI Tesseract on top-40% of each page (~5-10× faster)
    fast=False → full-quality sequential OCR on the whole page
    """
    extractor = PDFTextExtractor()
    presplitter = AwbDocumentPreSplitter(extractor=extractor)
    if fast:
        return presplitter.presplit_pdf_fast(raw_pdf)
    return presplitter.presplit_pdf_with_text(raw_pdf, use_extractor=True)


# ── Main page ──────────────────────────────────────────────────────────────
def render_pdf_upload(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">PDF workflow</div>
            <h1>AWB extraction</h1>
            <p>Upload a PDF — Claude Vision automatically detects and fills all AWB fields.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to Home", type="secondary"):
        on_back()
        st.stop()

    # ── Session state defaults ─────────────────────────────────────────────
    for key, val in {
        "raw_pdf_bytes": None,
        "pdf_name": None,
        "split_documents": None,
        "split_mode": "fast",
        "awb_results": None,
        "vision_refined_awbs": {},
        "debug_page_texts": None,
        "debug_pdf_name": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # ── Upload ─────────────────────────────────────────────────────────────
    uploaded = st.file_uploader("Select a PDF", type=["pdf"])
    if not uploaded:
        st.info("Upload a PDF to get started.")
        return

    raw_pdf = uploaded.read()

    # Reset everything when a new file is uploaded
    if st.session_state.get("pdf_name") != uploaded.name:
        st.session_state["pdf_name"] = uploaded.name
        st.session_state["raw_pdf_bytes"] = raw_pdf
        st.session_state["split_documents"] = None
        st.session_state["awb_results"] = None
        st.session_state["vision_refined_awbs"] = {}
        st.session_state["debug_page_texts"] = None
        st.session_state["debug_pdf_name"] = None
    else:
        st.session_state["raw_pdf_bytes"] = raw_pdf

    st.success(f"📄 {uploaded.name} — {uploaded.size:,} bytes")

    # ── Split mode selector ────────────────────────────────────────────────
    split_mode = st.radio(
        "Pre-split mode",
        options=["fast", "normale"],
        format_func=lambda x: (
            "⚡ Fast — 100 DPI, top 40% of page, parallel (recommended for scans)"
            if x == "fast"
            else "🔬 Normal — 200 DPI, full page, sequential (more accurate)"
        ),
        horizontal=True,
        key="split_mode_radio",
    )
    # If mode changed, force a re-split
    if split_mode != st.session_state.get("split_mode"):
        st.session_state["split_mode"] = split_mode
        st.session_state["split_documents"] = None
        st.session_state["awb_results"] = None
        st.session_state["vision_refined_awbs"] = {}
        st.session_state["debug_page_texts"] = None
        st.session_state["debug_pdf_name"] = None
        st.rerun()

    # ── Split ──────────────────────────────────────────────────────────────
    use_fast = (st.session_state["split_mode"] == "fast")
    if st.session_state["split_documents"] is None:
        mode_label = "⚡ fast" if use_fast else "🔬 normal"
        with st.spinner(f"Detecting AWB documents in the PDF ({mode_label})..."):
            try:
                docs = _split_pdf(raw_pdf, fast=use_fast)
                st.session_state["split_documents"] = docs
            except Exception as e:
                st.error(f"Split error: {e}")
                return

    split_docs: list[dict] = st.session_state["split_documents"]

    if not split_docs:
        st.error("No MAWB document found in the PDF. Please ensure the PDF contains an Air Waybill.")
        return

    awb_labels = [
        f"AWB {doc.get('awb_number') or '—'} (pag. {doc.get('start_page')}–{doc.get('end_page')})"
        for doc in split_docs
    ]
    st.info(f"**{len(split_docs)} document(s) detected:** {', '.join(d.get('awb_number') or '—' for d in split_docs)}")

    # ── Debug: raw text + split boundaries ────────────────────────────────
    with st.expander("🔍 Debug split — raw text per page", expanded=False):
        mode_badge = "⚡ Fast (100 DPI, top 40%)" if use_fast else "🔬 Normal (200 DPI, full page)"
        st.caption(
            f"Split mode used: **{mode_badge}**. "
            "Text extracted by pdfplumber/Tesseract (before Vision). "
            "Lines marked **\u2501\u2501 DOCUMENT START \u2026** indicate boundaries detected by the pre-splitter."
        )

        # Build a set of (page → doc_label) for quick lookup
        page_to_doc: dict[int, str] = {}
        for doc in split_docs:
            for p in range(doc.get("start_page", 1), doc.get("end_page", doc.get("start_page", 1)) + 1):
                page_to_doc[p] = doc.get("awb_number") or "—"

        # Re-extract raw page texts (cached in session state to avoid re-running)
        if "debug_page_texts" not in st.session_state or st.session_state.get("debug_pdf_name") != uploaded.name:
            import io as _io
            try:
                import pdfplumber as _pdfplumber
                raw_page_texts: dict[int, str] = {}
                with _pdfplumber.open(_io.BytesIO(raw_pdf)) as _pdf:
                    for i, _page in enumerate(_pdf.pages):
                        raw_page_texts[i + 1] = _page.extract_text() or "(no native text — scanned page)"
                st.session_state["debug_page_texts"] = raw_page_texts
                st.session_state["debug_pdf_name"] = uploaded.name
            except Exception as _e:
                st.warning(f"Could not extract raw text: {_e}")
                raw_page_texts = {}
        else:
            raw_page_texts = st.session_state["debug_page_texts"]

        if raw_page_texts:
            prev_doc = None
            for page_num in sorted(raw_page_texts.keys()):
                doc_label = page_to_doc.get(page_num, "—")
                if doc_label != prev_doc:
                    st.markdown(
                        f"<div style='background:#1e3a5f;color:#7dd3fc;padding:6px 10px;"
                        f"border-radius:4px;font-family:monospace;font-size:0.85rem;margin:8px 0 2px;'>"
                        f"━━ DOCUMENT START &nbsp;<strong>AWB {doc_label}</strong>"
                        f"&nbsp;━━</div>",
                        unsafe_allow_html=True,
                    )
                    prev_doc = doc_label

                with st.container():
                    st.markdown(
                        f"<span style='font-size:0.78rem;color:#94a3b8;'>Page {page_num}</span>",
                        unsafe_allow_html=True,
                    )
                    st.code(raw_page_texts[page_num], language=None)

    st.divider()

    # ── Extract All ────────────────────────────────────────────────────────
    col_extract, col_reset = st.columns([2, 1])
    with col_extract:
        extract_btn = st.button(
            f"🚀 Extract all ({len(split_docs)}) with Claude Vision",
            type="primary",
            use_container_width=True,
        )
    with col_reset:
        if st.button("🗑 Reset", type="secondary", use_container_width=True):
            st.session_state["awb_results"] = None
            st.session_state["vision_refined_awbs"] = {}
            st.rerun()

    if extract_btn:
        extractor = get_claude_vision()
        extracted: list[dict] = []  # each item: {"mawb": {...}, "hawbs": [...]}
        progress = st.progress(0, text="Starting...")
        errors: list[str] = []

        for i, doc in enumerate(split_docs):
            awb_num = doc.get("awb_number") or f"DOC_{i+1}"
            progress.progress(i / len(split_docs), text=f"Extracting {awb_num} ({i+1}/{len(split_docs)})...")
            try:
                result = extractor.extract_mawb_with_hawbs(
                    raw_pdf,
                    start_page=doc.get("start_page", 1),
                    end_page=doc.get("end_page", doc.get("start_page", 1)),
                )
                # Trust pre-validated AWB number from the splitter
                if doc.get("awb_number"):
                    result["mawb"]["awb_number"] = doc["awb_number"]
                extracted.append(result)
            except Exception as e:
                errors.append(f"{awb_num}: {e}")
                st.warning(f"⚠️ Error for {awb_num}: {e}")

        progress.progress(1.0, text="Done!")
        st.session_state["awb_results"] = extracted
        if errors:
            st.warning(f"{len(errors)} error(s) during extraction.")
        else:
            total_hawbs = sum(len(r.get("hawbs", [])) for r in extracted)
            st.success(f"✅ {len(extracted)} MAWB(s) extracted, {total_hawbs} HAWB(s) total")

    # ── Results ────────────────────────────────────────────────────────────
    if not st.session_state.get("awb_results"):
        return

    results: list[dict] = st.session_state["awb_results"]
    st.divider()
    total_hawbs_all = sum(len(r.get("hawbs", [])) for r in results)
    st.subheader(f"Results — {len(results)} MAWB, {total_hawbs_all} HAWB")

    for idx, result in enumerate(results):
        mawb_data = result.get("mawb", result)  # fallback: result itself is flat
        hawbs: list[dict] = result.get("hawbs", [])
        awb_num = mawb_data.get("awb_number") or f"AWB_{idx+1}"
        refined = st.session_state["vision_refined_awbs"].get(awb_num)
        display_mawb = refined.get("mawb", refined) if refined else mawb_data
        display_hawbs = refined.get("hawbs", hawbs) if refined else hawbs

        hawb_badge = f" • {len(display_hawbs)} HAWB" if display_hawbs else ""
        with st.expander(f"📦 MAWB {awb_num}{hawb_badge}", expanded=(idx == 0)):
            source_label = "🔮 Claude Vision (re-estratto)" if refined else "🔮 Claude Vision"
            st.success(source_label)

            # ── MAWB fields ──────────────────────────────────────────────
            st.markdown("#### 📋 Master Air Waybill")
            _awb_form(awb_num, display_mawb)

            # ── HAWB subsections ─────────────────────────────────────────
            if display_hawbs:
                st.divider()
                st.markdown(f"#### 🏠 House Air Waybills ({len(display_hawbs)})")
                for hi, hawb in enumerate(display_hawbs):
                    hawb_num = hawb.get("hawb_number") or f"HAWB_{hi+1}"
                    with st.expander(f"📜 HAWB {hawb_num}", expanded=True):
                        _hawb_form(hawb_num, hawb)
            else:
                st.caption("ℹ️ No House AWB detected in this block")

            st.divider()

            # Re-extract button
            if st.button("🔄 Re-extract with Vision (MAWB + HAWB)", key=f"reextract_{idx}", type="secondary"):
                try:
                    with st.spinner(f"Re-extracting {awb_num}..."):
                        ext = get_claude_vision()
                        doc = next((d for d in split_docs if (d.get("awb_number") or "") == awb_num), None)
                        if doc and st.session_state.get("raw_pdf_bytes"):
                            new_result = ext.extract_mawb_with_hawbs(
                                st.session_state["raw_pdf_bytes"],
                                start_page=doc.get("start_page", 1),
                                end_page=doc.get("end_page", doc.get("start_page", 1)),
                            )
                        else:
                            text = (doc or {}).get("text", "") if doc else ""
                            if not text:
                                raise ValueError("Source text not available")
                            flat = ext.extract_from_text(text)
                            new_result = {"mawb": flat, "hawbs": []}
                        new_result["mawb"]["awb_number"] = awb_num
                        st.session_state["vision_refined_awbs"][awb_num] = new_result
                        st.rerun()
                except Exception as e:
                    st.error(f"Re-extraction failed: {e}")

            # Download JSON (full: mawb + hawbs)
            full_json = json.dumps({"mawb": display_mawb, "hawbs": display_hawbs}, indent=2, default=str)
            st.download_button(
                label=f"⬇️ Download {awb_num} (JSON)",
                data=full_json,
                file_name=f"awb_{awb_num}.json",
                mime="application/json",
                key=f"dl_{idx}",
            )

            st.divider()

            # iCargo comparison (MAWB only)
            st.markdown("**📊 Compare with iCargo (MAWB)**")
            if st.button("Fetch & Compare iCargo", key=f"icargo_{idx}", type="primary"):
                if awb_num and "-" in awb_num:
                    try:
                        with st.spinner(f"Fetching {awb_num} from iCargo..."):
                            ic = ICargoIBSClient()
                            icargo_result = ic.get_awb(awb_num)
                            icargo_flat = map_icargo_awb_ibs(icargo_result)
                            rows = diff_awb(display_mawb, icargo_flat)
                            st.dataframe(rows, use_container_width=True)
                            mismatches = [r for r in rows if not r["match"]]
                            if not mismatches:
                                    st.success("✅ No differences found!")
                                else:
                                    st.warning(f"⚠️ {len(mismatches)} difference(s)")
                    except Exception as e:
                        st.error(f"iCargo error: {e}")
                else:
                    st.warning("Invalid AWB number for iCargo query")
    # ── Batch download ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("📥 Batch download")

    all_json = json.dumps(results, indent=2, default=str)
    st.download_button(
        label="⬇️ Download all (JSON)",
        data=all_json,
        file_name=f"awbs_batch_{len(results)}.json",
        mime="application/json",
    )

    try:
        import pandas as pd
        # Flatten: one row per MAWB with hawb_count
        flat_rows = []
        for r in results:
            row = dict(r.get("mawb", r))
            row["hawb_count"] = len(r.get("hawbs", []))
            flat_rows.append(row)
        df = pd.DataFrame(flat_rows)
        st.download_button(
            label="⬇️ Download MAWB summary (CSV)",
            data=df.to_csv(index=False),
            file_name=f"awbs_batch_{len(results)}.csv",
            mime="text/csv",
        )
    except Exception:
        pass
