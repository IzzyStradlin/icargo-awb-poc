# app/ui/pages/pdf_upload.py
from __future__ import annotations

import os
import re
import json
import hashlib
from typing import Optional

import streamlit as st
import requests
from dotenv import load_dotenv

from app.extraction.pdf_text_extractor import PDFTextExtractor, ExtractOptions
from app.extraction.awb_section_extractor import AwbSectionExtractor
from app.llm.phi3_local_provider import Phi3LocalProvider
from app.llm.cohere_provider import CohereProvider
from app.interpretation.awb_llm_parser import parse_llm_json
from app.interpretation.awb_hybrid_extractor import AwbHybridExtractor
from app.compare.awb_diff_ibs import map_extracted_awb_llm, map_icargo_awb_ibs, diff_awb

load_dotenv()


# =========================================================
# Cached LLM instances (avoid reloading models each rerun)
# =========================================================
@st.cache_resource
def get_phi3_llm() -> Phi3LocalProvider:
    return Phi3LocalProvider()


@st.cache_resource
def get_cohere_llm() -> CohereProvider:
    return CohereProvider()


def get_llm():
    """Returns the LLM provider selected by the user in the sidebar"""
    llm_choice = st.session_state.get("llm_choice", "Phi3 (Local)")
    
    if "Cohere" in llm_choice:
        return get_cohere_llm()
    else:
        return get_phi3_llm()


def clear_llm_cache():
    """Clears the cache of all LLM providers"""
    get_phi3_llm.clear()
    get_cohere_llm.clear()


def get_llm_display_name() -> str:
    """Returns the display name of the selected LLM provider"""
    return st.session_state.get("llm_choice", "Phi3 (Local)")


# =========================================================
# Deterministic AWB extraction from OCR text
# =========================================================
AWB_RE = re.compile(r"\b([0-9OIl]{3})\s*[-]?\s*([0-9OIl]{8})\b")


def _fix_ocr_digits(s: str) -> str:
    return (
        s.replace("O", "0").replace("o", "0")
         .replace("I", "1").replace("l", "1")
    )


def awb_candidates_from_text(text: str):
    cands = []
    for m in AWB_RE.finditer(text or ""):
        p = _fix_ocr_digits(m.group(1))
        n = _fix_ocr_digits(m.group(2))
        if p.isdigit() and n.isdigit():
            cands.append(f"{p}-{n}")

    # dedup preserving order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def best_awb_from_text(text: str) -> Optional[str]:
    cands = awb_candidates_from_text(text)
    return cands[0] if cands else None


# =========================================================
# IBS iCargo client (authenticate -> id_token -> GET AWB)
# =========================================================
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
        payload = {"username": self.username, "password": self.password}
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Auth error: {r.status_code} {r.text}")
        data = r.json()
        self.token = data["body"]["security"]["id_token"]

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


# =========================================================
# UI
# =========================================================
def render_pdf_upload(on_back):
    st.title("📄 Upload PDF")

    if st.button("⬅️ Back"):
        on_back()
        st.stop()

    # ---------- init session state ----------
    defaults = {
        "pdf_hash": None,
        "options_hash": None,
        "extracted_text": None,
        "used_ocr": False,
        "pdf_sections": None,
        "awb_struct": None,
        "llm_raw": None,
        "awb_from_ocr": None,
        "awb_candidates_ocr": [],
        "awb_selected": None,
        "icargo_awb": None,
        "diff_rows": None,
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

    # ---------- detect changes (PDF or options) ----------
    pdf_hash = hashlib.sha256(raw_pdf).hexdigest()
    opt_blob = json.dumps({
        "force_ocr": force_ocr,
        "min_chars": min_chars,
        "ocr_lang": ocr_lang,
        "ocr_dpi": int(ocr_dpi),
        "max_pages": int(max_pages),
    }, sort_keys=True).encode("utf-8")
    options_hash = hashlib.sha256(opt_blob).hexdigest()

    if st.session_state.pdf_hash != pdf_hash or st.session_state.options_hash != options_hash:
        st.session_state.pdf_hash = pdf_hash
        st.session_state.options_hash = options_hash

        st.session_state.extracted_text = None
        st.session_state.used_ocr = False
        st.session_state.pdf_sections = None

        st.session_state.awb_struct = None
        st.session_state.llm_raw = None

        st.session_state.icargo_awb = None
        st.session_state.diff_rows = None
        st.session_state.awb_selected = None

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

        # Also extract sections from PDF (for section-aware field detection)
        with st.spinner("Extracting document sections..."):
            try:
                section_extractor = AwbSectionExtractor()
                sections = section_extractor.extract_sections(raw_pdf, max_pages=int(max_pages) if int(max_pages) > 0 else None)
                st.session_state.pdf_sections = sections
            except Exception as e:
                st.warning(f"Could not extract sections: {e}. Using flat text extraction.")
                st.session_state.pdf_sections = None

    text = st.session_state.extracted_text
    used_ocr = st.session_state.used_ocr

    st.success(f"Loaded: {uploaded.name} ({uploaded.size} bytes)")
    st.caption("OCR used: ✅" if used_ocr else "OCR used: ❌")

    st.subheader("1) Extracted Text")
    st.text_area("Text Output", value=text, height=250)

    # ---------- AWB from OCR ALWAYS ----------
    st.session_state.awb_candidates_ocr = awb_candidates_from_text(text)
    st.session_state.awb_from_ocr = best_awb_from_text(text)

    with st.expander("AWB candidates (OCR regex debug)", expanded=False):
        st.write(st.session_state.awb_candidates_ocr)

    st.divider()

    # ---------- LLM extraction ONLY on button ----------
    st.subheader("2) AWB Data Reconstruction (LLM)")

    llm_display = get_llm_display_name()
    
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        run_llm = st.button(f"Run LLM Reconstruction ({llm_display})")
    with colB:
        clear_llm = st.button("Reset LLM")
    with colC:
        reload_llm = st.button(f"🔄 Reload {llm_display} (clear cache)")

    if reload_llm:
        # IMPORTANT: removes the cached model instance
        clear_llm_cache()
        st.session_state.awb_struct = None
        st.session_state.llm_raw = None
        st.session_state.icargo_awb = None
        st.session_state.diff_rows = None
        st.success(f"Cache {llm_display} cleared. Now re-run the LLM extraction.")

    if clear_llm:
        st.session_state.awb_struct = None
        st.session_state.llm_raw = None
        st.session_state.icargo_awb = None
        st.session_state.diff_rows = None

    if run_llm:
        try:
            with st.spinner("Hybrid extraction (rule-based + LLM) in progress..."):
                # ✅ Use the hybrid extractor: combines rules + LLM for better results
                llm_provider = get_llm()
                # Pass sections if available for section-aware extraction
                sections = st.session_state.get("pdf_sections")
                extracted_data = AwbHybridExtractor(llm_provider=llm_provider).extract(text, sections=sections)

            st.session_state.awb_struct = extracted_data

        except Exception as e:
            st.error(f"Extraction failed: {e}")
            import traceback
            traceback.print_exc()

    if st.session_state.awb_struct is not None:
        st.success("LLM Reconstruction available (session_state)")
        with st.expander("Full LLM JSON (debug)", expanded=False):
            st.json(st.session_state.awb_struct)
    else:
        st.warning("LLM not yet executed (or reset).")

    st.divider()

    # ---------- AWB selection: OCR wins, then LLM, with manual override ----------
    st.subheader("3) AWB Number (key for iCargo call)")

    awb_llm = None
    if st.session_state.awb_struct:
        awb_llm = st.session_state.awb_struct.get("awb_number")

    default_awb = st.session_state.awb_from_ocr or awb_llm or ""
    if st.session_state.awb_from_ocr:
        st.info(f"AWB from OCR (deterministic): **{st.session_state.awb_from_ocr}**")
    elif awb_llm:
        st.info(f"AWB from LLM: **{awb_llm}**")
    else:
        st.warning("AWB not found automatically (neither OCR nor LLM).")

    manual = st.text_input("Manual AWB Override (if needed)", value=st.session_state.awb_selected or default_awb)
    awb_selected = manual.strip() or None

    # normalize 00133412551 -> 001-33412551
    if awb_selected and "-" not in awb_selected and awb_selected.isdigit() and len(awb_selected) == 11:
        awb_selected = f"{awb_selected[:3]}-{awb_selected[3:]}"

    st.session_state.awb_selected = awb_selected

    if not awb_selected:
        st.error("AWB not available: cannot call iCargo yet.")
        return

    st.success(f"Selected AWB: {awb_selected}")

    st.divider()

    # ---------- iCargo GET: ONLY on button ----------
    st.subheader("4) Fetch AWB from iCargo (IBS) + Diff")
    st.caption("This button does NOT call Phi-3: only uses session_state.")

    col1, col2 = st.columns([1, 1])
    with col1:
        fetch_icargo = st.button("Fetch AWB from iCargo")
    with col2:
        clear_icargo = st.button("Reset iCargo/Diff")

    if clear_icargo:
        st.session_state.icargo_awb = None
        st.session_state.diff_rows = None

    if fetch_icargo:
        try:
            with st.spinner("Calling iCargo IBS..."):
                ic = ICargoIBSClient()
                st.session_state.icargo_awb = ic.get_awb(awb_selected)
            st.success("iCargo AWB received and saved in session_state")
        except Exception as e:
            st.error(f"iCargo GET Error: {e}")

    if st.session_state.icargo_awb is not None:
        with st.expander("iCargo AWB JSON (debug)", expanded=False):
            st.json(st.session_state.icargo_awb)

    # ---------- Diff ----------
    if st.session_state.awb_struct is None:
        st.warning("Diff available only after running LLM (Phi-3).")
        return

    if st.session_state.icargo_awb is None:
        st.warning("Press 'Fetch AWB from iCargo' to calculate the diff.")
        return

    extracted_flat = map_extracted_awb_llm(st.session_state.awb_struct)

    # for safety: force awb_number from selected (OCR/manual)
    extracted_flat["awb_number"] = awb_selected
    st.session_state.awb_struct["awb_number"] = awb_selected

    icargo_flat = map_icargo_awb_ibs(st.session_state.icargo_awb)

    rows = diff_awb(extracted_flat, icargo_flat)
    st.session_state.diff_rows = rows

    st.subheader("Differences (PDF/LLM vs iCargo)")
    st.dataframe(rows, width='stretch')

    mism = [r for r in rows if not r["match"]]
    if not mism:
        st.success("✅ No differences on compared fields")
    else:
        st.warning(f"⚠️ Differences found: {len(mism)}")
        st.dataframe(mism, width='stretch')

    with st.expander("DEBUG extracted_flat / icargo_flat", expanded=False):
        st.json({"extracted_flat": extracted_flat, "icargo_flat": icargo_flat})