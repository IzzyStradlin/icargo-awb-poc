import streamlit as st
from app.llm.phi3_local_provider import Phi3LocalProvider
from app.llm.cohere_provider import CohereProvider


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


def render_email_upload(on_back):
    st.title("✉️ Email Upload (.eml)")

    if st.button("⬅️ Back"):
        on_back()
        st.stop()

    uploaded = st.file_uploader("Select an email file .eml", type=["eml"])

    if uploaded:
        st.success(f"Loaded: {uploaded.name} ({uploaded.size} bytes)")
        raw_eml = uploaded.read()

        # Placeholder: here you will connect .eml parsing / body extraction + attachments / AWB pipeline.
        st.info("TODO: connect .eml parsing / body extraction + attachments / AWB pipeline.")
        st.write("Preview bytes:", len(raw_eml))