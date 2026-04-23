import streamlit as st
from app.interpretation.awb_vision_extractor import AwbVisionExtractor


@st.cache_resource
def get_claude_vision() -> AwbVisionExtractor:
    return AwbVisionExtractor()


def render_email_upload(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">Email workflow</div>
            <h1>Email message intake</h1>
            <p>Import .eml files and prepare email body and attachments for further document processing.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to Home"):
        on_back()
        st.stop()

    uploaded = st.file_uploader("Select an email file .eml", type=["eml"])

    if uploaded:
        st.success(f"Loaded: {uploaded.name} ({uploaded.size} bytes)")
        raw_eml = uploaded.read()

        # Placeholder: here you will connect .eml parsing / body extraction + attachments / AWB pipeline.
        st.info("TODO: connect .eml parsing / body extraction + attachments / AWB pipeline.")
        st.write("Preview bytes:", len(raw_eml))