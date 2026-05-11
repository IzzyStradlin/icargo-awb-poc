# app/ui/pages/pdf_upload.py
"""
PDF → Claude Vision → AWB extraction.
Flow: upload PDF → auto-split by MAWB → Claude Vision per document → results.
No OCR step exposed to user. No Cohere. No regex parsing.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv

from app.extraction.pdf_text_extractor import PDFTextExtractor
from app.extraction.awb_document_presplitter import AwbDocumentPreSplitter
from app.interpretation.awb_vision_extractor import AwbVisionExtractor
from app.compare.awb_diff_ibs import map_icargo_awb_ibs, diff_awb, map_icargo_hawb_ibs, diff_hawb
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

    def get_hawbs(self, mawb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{mawb_code}/hawbs"
        r = requests.get(url, headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Error GET HAWBs: {r.status_code} {r.text}")
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
    fast=True  → parallel 300 DPI Tesseract on top 20% of each page (recommended)
    fast=False → full-quality sequential OCR on the whole page (difficult scans)
    """
    extractor = PDFTextExtractor()
    presplitter = AwbDocumentPreSplitter(extractor=extractor)
    if fast:
        return presplitter.presplit_pdf_fast(raw_pdf)
    return presplitter.presplit_pdf_with_text(raw_pdf, use_extractor=True)


def _extract_pdfs_from_upload(uploaded) -> list[dict]:
    """
    Normalises a file upload to a list of {"name": str, "bytes": bytes} dicts.
    Accepts a single PDF or a ZIP archive containing one or more PDFs.
    Files inside the ZIP are sorted by name for deterministic ordering.
    Non-PDF entries and macOS metadata folders inside the ZIP are silently skipped.
    """
    raw = uploaded.read()
    if uploaded.name.lower().endswith(".zip"):
        results = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            pdf_entries = sorted(
                name for name in zf.namelist()
                if name.lower().endswith(".pdf") and not name.startswith("__MACOSX")
            )
            for entry in pdf_entries:
                results.append({"name": entry.split("/")[-1], "bytes": zf.read(entry)})
        return results
    return [{"name": uploaded.name, "bytes": raw}]


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
        "batch_pdfs": [],
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
    uploaded = st.file_uploader(
        "Select a PDF or a ZIP archive containing PDFs",
        type=["pdf", "zip"],
    )
    if not uploaded:
        st.info("Upload a PDF or a ZIP archive containing PDFs to get started.")
        return

    # Normalise upload → list of PDFs; only re-parse when the file changes.
    if st.session_state.get("pdf_name") != uploaded.name:
        batch_pdfs = _extract_pdfs_from_upload(uploaded)
        if not batch_pdfs:
            st.error("No PDF files found in the archive.")
            return
        st.session_state["pdf_name"] = uploaded.name
        st.session_state["batch_pdfs"] = batch_pdfs
        st.session_state["raw_pdf_bytes"] = batch_pdfs[0]["bytes"]
        st.session_state["split_documents"] = None
        st.session_state["awb_results"] = None
        st.session_state["vision_refined_awbs"] = {}
        st.session_state["debug_page_texts"] = None
        st.session_state["debug_pdf_name"] = None

    batch_pdfs: list[dict] = st.session_state["batch_pdfs"]
    if not batch_pdfs:
        st.error("No PDF files to process. Please re-upload the file.")
        return

    # raw_pdf kept for single-file features (debug panel, PNG preview)
    raw_pdf = batch_pdfs[0]["bytes"]
    is_zip = uploaded.name.lower().endswith(".zip")

    if is_zip:
        st.success(f"📦 {uploaded.name} — {len(batch_pdfs)} PDF file(s) found")
        with st.expander("📄 Files in archive", expanded=False):
            for p in batch_pdfs:
                st.caption(f"• {p['name']} ({len(p['bytes']):,} bytes)")
    else:
        st.success(f"📄 {uploaded.name} — {uploaded.size:,} bytes")

    # ── Split mode selector ────────────────────────────────────────────────
    split_mode = st.radio(
        "Pre-split mode",
        options=["fast", "normale"],
        format_func=lambda x: (
            "⚡ Smart — 300 DPI, top 20% of page, parallel (recommended)"
            if x == "fast"
            else "🔬 Normal — 200 DPI, full page, sequential (for difficult scans)"
        ),
        horizontal=True,
        key="split_mode_radio",
    )
    # If mode changed, force a re-split (keep batch_pdfs — they come from the file)
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
        mode_label = "⚡ smart" if use_fast else "🔬 normal"
        src_label = f"{len(batch_pdfs)} PDF(s)" if is_zip else "the PDF"
        with st.spinner(f"Detecting AWB documents in {src_label} ({mode_label})..."):
            try:
                all_docs: list[dict] = []
                for pdf_entry in batch_pdfs:
                    docs = _split_pdf(pdf_entry["bytes"], fast=use_fast)
                    for doc in docs:
                        # Tag each split document with its source PDF so the
                        # extraction step can use the correct PDF bytes.
                        doc["_pdf_name"] = pdf_entry["name"]
                        doc["_pdf_bytes"] = pdf_entry["bytes"]
                    all_docs.extend(docs)
                st.session_state["split_documents"] = all_docs
            except Exception as e:
                st.error(f"Split error: {e}")
                return

    split_docs: list[dict] = st.session_state["split_documents"]

    if not split_docs:
        st.error("No MAWB document found in the PDF. Please ensure the PDF contains an Air Waybill.")
        return

    st.info(f"**{len(split_docs)} document(s) detected:** {', '.join(d.get('awb_number') or '—' for d in split_docs)}")

    # ── Debug: raw text + split boundaries ────────────────────────────────
    with st.expander("🔍 Debug split — raw text per page", expanded=False):
        if is_zip:
            st.info(
                f"Showing raw page text for the first PDF in the archive "
                f"(**{batch_pdfs[0]['name']}**) only."
            )
        mode_badge = "⚡ Smart (300 DPI, top 20%)" if use_fast else "🔬 Normal (200 DPI, full page)"
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

    # ── Preview rendered PNGs (rotation-corrected, no Claude call) ─────────
    with st.expander("🖼 Preview rendered pages (rotation check — no Claude call)", expanded=False):
        st.caption(
            "Downloads a ZIP of the PNG images that would be sent to Claude Vision. "
            "Use this to verify orientation correction before spending API credits."
        )
        if st.button("📦 Build PNG preview ZIP", key="build_png_zip"):
            import io as _zip_io
            import zipfile as _zipfile
            try:
                import fitz as _fitz
            except ImportError:
                st.error("PyMuPDF not installed. Run: pip install pymupdf")
                return

            buf = _zip_io.BytesIO()
            total_pages = 0
            with _zipfile.ZipFile(buf, "w", compression=_zipfile.ZIP_DEFLATED) as zf:
                # Track the currently open fitz document to avoid re-opening
                # the same PDF repeatedly when multiple split_docs share a source.
                _current_pdf_bytes = None
                _fitz_doc = None
                for doc_idx, doc in enumerate(split_docs):
                    doc_pdf_bytes = doc.get("_pdf_bytes") or raw_pdf
                    if doc_pdf_bytes is not _current_pdf_bytes:
                        if _fitz_doc:
                            _fitz_doc.close()
                        _fitz_doc = _fitz.open(stream=doc_pdf_bytes, filetype="pdf")
                        _current_pdf_bytes = doc_pdf_bytes
                    awb_label = doc.get("awb_number") or f"DOC_{doc_idx + 1}"
                    # In ZIP/batch mode prefix with the source PDF name for clarity
                    if is_zip and doc.get("_pdf_name"):
                        pdf_stem = doc["_pdf_name"].rsplit(".", 1)[0]
                        awb_label = f"{pdf_stem}/{awb_label}"
                    rotations: dict = doc.get("page_rotations") or {}
                    s = doc.get("start_page", 1)
                    e = doc.get("end_page", s)
                    _prev_correction = 0  # carry-forward for ambiguous pages within this doc
                    for page_num_1 in range(s, e + 1):
                        fitz_idx = page_num_1 - 1
                        if fitz_idx >= len(_fitz_doc):
                            continue
                        page = _fitz_doc[fitz_idx]
                        if page_num_1 in rotations:
                            correction = rotations[page_num_1]
                        else:
                            # Gradient orientation: compare score(0°) vs score(90°) directly.
                            # (Pair sums are always equal — mathematical identity.)
                            correction = _prev_correction  # carry-forward default
                            try:
                                import numpy as _np

                                def _gscore(px):
                                    a = _np.frombuffer(px.samples, dtype=_np.uint8).reshape(px.height, px.width, 3)
                                    d = (a.mean(axis=2) < 180).astype(_np.float32)
                                    cv = float(d.sum(axis=0).var())
                                    return float(d.sum(axis=1).var()) / (cv if cv > 0 else 1.0)

                                _lm = _fitz.Matrix(0.75, 0.75)
                                _s0 = _gscore(page.get_pixmap(matrix=_lm, colorspace=_fitz.csRGB))
                                _s90 = _gscore(page.get_pixmap(matrix=_lm.prerotate(90), colorspace=_fitz.csRGB))
                                if _s90 > _s0 * 1.15:
                                    correction = 90
                                elif _s0 > _s90 * 1.15:
                                    correction = 0
                            except Exception:
                                pass  # keep carry-forward
                        _prev_correction = correction
                        mat = _fitz.Matrix(1.5, 1.5).prerotate(correction) if correction else _fitz.Matrix(1.5, 1.5)
                        pix = page.get_pixmap(matrix=mat, colorspace=_fitz.csRGB)
                        png_bytes = pix.tobytes("png")
                        rot_label = f"_rot{correction}" if correction else ""
                        fname = f"{awb_label}/page_{page_num_1:03d}{rot_label}.png"
                        zf.writestr(fname, png_bytes)
                        total_pages += 1
                if _fitz_doc:
                    _fitz_doc.close()

            buf.seek(0)
            st.download_button(
                label=f"⬇️ Download {total_pages} PNG(s) as ZIP",
                data=buf.getvalue(),
                file_name=f"{uploaded.name.rsplit('.', 1)[0]}_preview.zip",
                mime="application/zip",
                key="download_png_zip",
            )
            st.success(f"✅ {total_pages} page(s) rendered. Check the ZIP to verify orientation.")

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
                    doc.get("_pdf_bytes") or raw_pdf,
                    start_page=doc.get("start_page", 1),
                    end_page=doc.get("end_page", doc.get("start_page", 1)),
                    page_rotations=doc.get("page_rotations"),
                )
                # Trust pre-validated AWB number from the splitter
                if doc.get("awb_number"):
                    result["mawb"]["awb_number"] = doc["awb_number"]
                # Carry the source PDF name through to the results for display
                result["_pdf_name"] = doc.get("_pdf_name", "")
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
        pdf_badge = f"  [{result.get('_pdf_name')}]" if is_zip and result.get("_pdf_name") else ""
        with st.expander(f"📦 MAWB {awb_num}{hawb_badge}{pdf_badge}", expanded=(idx == 0)):
            source_label = "🔮 Claude Vision (re-extracted)" if refined else "🔮 Claude Vision"
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
                        doc_pdf_bytes = doc.get("_pdf_bytes") if doc else None
                        if doc and doc_pdf_bytes:
                            new_result = ext.extract_mawb_with_hawbs(
                                doc_pdf_bytes,
                                start_page=doc.get("start_page", 1),
                                end_page=doc.get("end_page", doc.get("start_page", 1)),
                                page_rotations=doc.get("page_rotations"),
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

            # iCargo comparison (MAWB + HAWBs)
            st.markdown("**📊 Compare with iCargo (MAWB + HAWBs)**")
            if st.button("Fetch & Compare iCargo", key=f"icargo_{idx}", type="primary"):
                if awb_num and "-" in awb_num:
                    try:
                        ic = ICargoIBSClient()

                        # ── MAWB comparison ──────────────────────────────────
                        with st.spinner(f"Fetching MAWB {awb_num} from iCargo..."):
                            icargo_result = ic.get_awb(awb_num)
                        icargo_flat = map_icargo_awb_ibs(icargo_result)
                        rows = diff_awb(display_mawb, icargo_flat)
                        st.markdown("##### MAWB")
                        st.dataframe(rows, use_container_width=True)
                        mawb_mismatches = [r for r in rows if not r["match"]]
                        if not mawb_mismatches:
                            st.success("✅ MAWB — no differences!")
                        else:
                            st.warning(f"⚠️ MAWB — {len(mawb_mismatches)} difference(s)")

                        # ── HAWB comparison ──────────────────────────────────
                        if display_hawbs:
                            st.markdown("##### HAWBs")
                            hawbs_resp = None
                            with st.spinner(f"Fetching HAWBs for {awb_num} from iCargo..."):
                                try:
                                    hawbs_resp = ic.get_hawbs(awb_num)
                                except Exception as he:
                                    st.warning(f"⚠️ Could not fetch HAWBs from iCargo: {he}")

                            if hawbs_resp is not None:
                                # ── Normalise response to a flat list ─────────────────
                                def _flatten_hawbs_resp(resp) -> list:
                                    if isinstance(resp, list):
                                        return resp
                                    if not isinstance(resp, dict):
                                        return []
                                    # Try common top-level keys
                                    for key in ("hawbs", "body", "data", "items", "result", "results"):
                                        val = resp.get(key)
                                        if isinstance(val, list) and val:
                                            return val
                                        if isinstance(val, dict):
                                            # one more level: e.g. {"body": {"hawbs": [...]}}
                                            inner = _flatten_hawbs_resp(val)
                                            if inner:
                                                return inner
                                    return []

                                ic_hawb_list = _flatten_hawbs_resp(hawbs_resp)

                                # ── Raw iCargo debug info ──────────────────────────────
                                with st.expander(
                                    f"🔎 iCargo response — {len(ic_hawb_list)} HAWB(s) ricevuti",
                                    expanded=False,
                                ):
                                    st.json(hawbs_resp)

                                def _ic_num(h: dict) -> str:
                                    return str(
                                        h.get("hawb")
                                        or h.get("hawb_number")
                                        or h.get("hawbNumber")
                                        or h.get("houseAirwaybillNumber")
                                        or h.get("hawbNo")
                                        or ""
                                    ).strip()

                                def _norm_hawb_key(n: str) -> str:
                                    return re.sub(r"[\s\-]", "", n).lstrip("0").upper()

                                # Build lookup: normalised_key → (original_num, iCargo record)
                                ic_by_norm: dict[str, tuple[str, dict]] = {}
                                for h in ic_hawb_list:
                                    if isinstance(h, dict):
                                        raw = _ic_num(h)
                                        if raw:
                                            ic_by_norm[_norm_hawb_key(raw)] = (raw, h)

                                # If number-based matching finds ZERO matches, fall back
                                # to positional so the user always sees something.
                                pdf_norms = [
                                    _norm_hawb_key(hawb.get("hawb_number") or f"HAWB_{hi+1}")
                                    for hi, hawb in enumerate(display_hawbs)
                                ]
                                matched_count = sum(1 for k in pdf_norms if k in ic_by_norm)
                                use_positional = (matched_count == 0 and len(ic_hawb_list) > 0)
                                if use_positional:
                                    st.warning(
                                        "⚠️ Nessun numero HAWB corrisponde tra PDF e iCargo. "
                                        "Confronto posizionale (1°↔1°, 2°↔2°…). "
                                        "Verifica i numeri nel pannello debug qui sopra."
                                    )

                                pdf_nums_seen: set[str] = set()  # tracks normalised keys

                                # ── PDF HAWBs: matched or PDF-only orphan ──────────────
                                for hi, hawb in enumerate(display_hawbs):
                                    hawb_num_key = hawb.get("hawb_number") or f"HAWB_{hi + 1}"
                                    norm_key = _norm_hawb_key(hawb_num_key)
                                    pdf_nums_seen.add(norm_key)

                                    if use_positional:
                                        ic_hawb = ic_hawb_list[hi] if hi < len(ic_hawb_list) else None
                                        ic_label = _ic_num(ic_hawb) if ic_hawb else "—"
                                    else:
                                        ic_entry = ic_by_norm.get(norm_key)
                                        ic_hawb = ic_entry[1] if ic_entry else None
                                        ic_label = ic_entry[0] if ic_entry else None

                                    if ic_hawb is not None:
                                        label_suffix = (
                                            f" ↔ iCargo {ic_label}" if ic_label and ic_label != hawb_num_key else ""
                                        )
                                        ic_hawb_flat = map_icargo_hawb_ibs(ic_hawb)
                                        hawb_rows = diff_hawb(hawb, ic_hawb_flat)
                                        st.markdown(f"###### {hawb_num_key}{label_suffix}")
                                        st.dataframe(hawb_rows, use_container_width=True)
                                        hawb_mismatches = [r for r in hawb_rows if not r["match"]]
                                        if not hawb_mismatches:
                                            st.success(f"✅ {hawb_num_key} — no differences!")
                                        else:
                                            st.warning(f"⚠️ {hawb_num_key} — {len(hawb_mismatches)} difference(s)")
                                    else:
                                        # Orphan: in PDF, not found in iCargo
                                        st.markdown(f"###### 🔍 {hawb_num_key} — solo PDF")
                                        ic_hawb_flat = map_icargo_hawb_ibs({})
                                        hawb_rows = diff_hawb(hawb, ic_hawb_flat)
                                        st.dataframe(hawb_rows, use_container_width=True)

                                # ── iCargo HAWBs not matched to any PDF HAWB ──────────
                                if not use_positional:
                                    for norm_k, (ic_num, ic_hawb) in ic_by_norm.items():
                                        if norm_k not in pdf_nums_seen:
                                            st.markdown(f"###### 🔍 {ic_num} — solo iCargo")
                                            ic_hawb_flat = map_icargo_hawb_ibs(ic_hawb)
                                            hawb_rows = diff_hawb({}, ic_hawb_flat)
                                            st.dataframe(hawb_rows, use_container_width=True)

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
            if is_zip and r.get("_pdf_name"):
                row["source_pdf"] = r["_pdf_name"]
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
