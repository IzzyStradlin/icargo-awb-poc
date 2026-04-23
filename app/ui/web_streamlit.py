import streamlit as st
import os

from dotenv import load_dotenv
load_dotenv()

# Import MSC Branding
from app.ui.assets.branding import get_brand_info, get_css, get_logo_data_uri

# Import pages
from app.ui.pages.pdf_upload import render_pdf_upload
from app.ui.pages.email_upload import render_email_upload

# Configure Streamlit
st.set_page_config(
    page_title=f"{get_brand_info()['company_name']} - {get_brand_info()['product_name']}", 
    layout="wide",
    initial_sidebar_state="expanded",
)

# Apply MSC branding CSS
st.markdown(get_css(), unsafe_allow_html=True)

# =========================================================
# LLM Configuration in sidebar
# =========================================================
with st.sidebar:
    brand = get_brand_info()
    st.markdown(f"## {brand['company_name']}")
    st.caption(brand["product_name"])
    st.divider()
    st.markdown("### Configuration")
    st.info("🔮 AI Engine: **Claude Vision**")
    st.divider()
    st.markdown(
        f"<div class='msc-footer'>{brand['copyright']}<br><span>Version {brand['version']}</span></div>",
        unsafe_allow_html=True,
    )

def set_page(page_name: str):
    st.session_state["page"] = page_name

def render_landing():
    brand = get_brand_info()
    logo_uri = get_logo_data_uri()
    logo_html = ""
    if logo_uri:
        logo_html = (
            "<div class='msc-logo-chip'>"
            f"<img src='{logo_uri}' alt='MSC Air Cargo logo'>"
            "</div>"
        )

    st.markdown(
        f"""
        <div class="msc-shell">
            <section class="msc-hero">
                <div class="msc-hero-inner">
                    {logo_html}
                    <div class="msc-eyebrow">MSC air cargo workflow</div>
                    <h1>{brand['product_name']}</h1>
                    <p>{brand['tagline']}. Upload PDFs or emails, split AWB documents, extract key data and prepare the comparison with iCargo in a single operational experience.</p>
                    <div class="msc-stat-grid">
                        <div class="msc-stat">
                            <strong>AWB Splitting</strong>
                            <span>Multi-document separation before extraction.</span>
                        </div>
                        <div class="msc-stat">
                            <strong>OCR Visibility</strong>
                            <span>Raw JSON and XML for debugging and audit.</span>
                        </div>
                        <div class="msc-stat">
                            <strong>Operational Review</strong>
                            <span>Pipeline designed for cargo verification and data quality.</span>
                        </div>
                    </div>
                </div>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='msc-kicker'>Select workflow</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown(
            """
            <div class="msc-panel">
                <div class="msc-kicker">Workflow 01</div>
                <h3>PDF intake</h3>
                <p>Upload AWB documents and related attachments, run OCR, split and structured analysis in a single flow.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open PDF Workflow", key="btn_pdf", use_container_width=True):
            set_page("pdf_upload")

    with col2:
        st.markdown(
            """
            <div class="msc-panel">
                <div class="msc-kicker">Workflow 02</div>
                <h3>Email intake</h3>
                <p>Import .eml files, isolate the operational content and prepare attachments and body for further processing.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Email Workflow", key="btn_email", use_container_width=True):
            set_page("email_upload")

    st.markdown(
        f"<div class='msc-footer'>{brand['copyright']}<br><span>Version {brand['version']}</span></div>",
        unsafe_allow_html=True,
    )

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