import streamlit as st

from dotenv import load_dotenv
load_dotenv()

# Import pages
from app.ui.pages.pdf_upload import render_pdf_upload
from app.ui.pages.email_upload import render_email_upload

st.set_page_config(page_title="iCargo AWB PoC", layout="wide")

# =========================================================
# LLM Configuration in sidebar
# =========================================================
with st.sidebar:
    st.header("⚙️ Configuration")
    st.selectbox(
        "Select LLM provider:",
        ["Phi3 (Local)", "Cohere (Cloud)"],
        key="llm_choice"
    )

def set_page(page_name: str):
    st.session_state["page"] = page_name

def render_landing():
    st.title("iCargo AWB PoC")
    st.write("Choose input type to load:")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📄 PDF")
        st.write("Load a PDF file (AWB / related documents).")
        if st.button("Load PDF", width='stretch'):
            set_page("pdf_upload")

    with col2:
        st.subheader("✉️ Email (.eml)")
        st.write("Load an email file in .eml format (with or without attachments).")
        if st.button("Load Email", width='stretch'):
            set_page("email_upload")

# Init page state
if "page" not in st.session_state:
    st.session_state["page"] = "landing"

# Simple router
page = st.session_state["page"]

if page == "pdf_upload":
    render_pdf_upload(on_back=lambda: set_page("landing"))
elif page == "email_upload":
    render_email_upload(on_back=lambda: set_page("landing"))
else:
    render_landing()