import logging
import streamlit as st
import os

from dotenv import load_dotenv
load_dotenv()

# Configure logging — set AWB_LOG_LEVEL=DEBUG (or INFO/WARNING) via env var.
# DEBUG shows per-page OSD rotation results and Claude rendering decisions.
_log_level = os.getenv("AWB_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Import MSC Branding
from app.ui.assets.branding import get_brand_info, get_css, get_logo_data_uri

# Import pages
from app.ui.pages.pdf_upload import render_pdf_upload
from app.ui.pages.email_upload import render_email_upload
from app.ui.pages.awb_lookup import render_awb_lookup
from app.ui.pages.flight_tracking import render_flight_tracking

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

    col1, col2, col3, col4, col5 = st.columns(5, gap="large")

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
        if st.button("Open PDF Workflow", key="btn_pdf", width='stretch'):
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
        if st.button("Open Email Workflow", key="btn_email", width='stretch'):
            set_page("email_upload")

    with col3:
        st.markdown(
            """
            <div class="msc-panel">
                <div class="msc-kicker">Workflow 03</div>
                <h3>Polling folder</h3>
                <p>Watch a shared folder, pick the next PDF automatically, process it, and move it to the processed area when the user confirms the update.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Polling Workflow", key="btn_polling", width='stretch'):
            st.session_state["folder_polling"] = True
            st.session_state["polling_input_dir"] = r"C:\TEMP\POC"
            st.session_state["polling_processed_dir"] = r"C:\TEMP\POC\PROCESSED"
            set_page("pdf_upload")

    with col4:
        st.markdown(
            """
            <div class="msc-panel">
                <div class="msc-kicker">Workflow 04</div>
                <h3>AWB Lookup</h3>
                <p>Query iCargo IBS directly by AWB number and inspect the raw JSON response in real time.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open AWB Lookup", key="btn_lookup", width='stretch'):
            set_page("awb_lookup")

    with col5:
        st.markdown(
            """
            <div class="msc-panel">
                <div class="msc-kicker">Workflow 05</div>
                <h3>Flight Tracking</h3>
                <p>Track a flight in real time by number and view its live position on an open map.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Flight Tracking", key="btn_flight_tracking", width='stretch'):
            set_page("flight_tracking")

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
elif page == "awb_lookup":
    render_awb_lookup(on_back=lambda: set_page("landing"))
elif page == "flight_tracking":
    render_flight_tracking(on_back=lambda: set_page("landing"))
else:
    render_landing()