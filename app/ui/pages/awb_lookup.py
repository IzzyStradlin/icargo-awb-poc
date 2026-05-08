"""
AWB Lookup page — retrieve a raw AWB record from iCargo IBS and display the JSON response.
"""
import json
import streamlit as st

from app.integration.icargo_ibs_client import ICargoIBSClient


@st.cache_resource
def _get_client() -> ICargoIBSClient:
    return ICargoIBSClient()


def render_awb_lookup(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">iCargo IBS — live query</div>
            <h1>AWB Lookup</h1>
            <p>Enter an AWB number to retrieve the raw record from iCargo and inspect the JSON response.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Home"):
        on_back()
        st.stop()

    st.divider()

    # ── Input form ────────────────────────────────────────────────────────────
    col_input, col_btn = st.columns([3, 1], gap="small")
    with col_input:
        awb_input = st.text_input(
            "AWB number",
            placeholder="233-10448211",
            label_visibility="collapsed",
        )
    with col_btn:
        search = st.button("🔍 Retrieve", use_container_width=True)

    if not search:
        st.stop()

    # ── Normalise AWB number (accept both "23310448211" and "233-10448211") ──
    awb_raw = awb_input.strip()
    if not awb_raw:
        st.warning("Please enter an AWB number.")
        st.stop()

    # Insert dash if missing (11 digits → NNN-NNNNNNNN)
    digits_only = awb_raw.replace("-", "").replace(" ", "")
    if digits_only.isdigit() and len(digits_only) == 11:
        awb_number = f"{digits_only[:3]}-{digits_only[3:]}"
    else:
        awb_number = awb_raw

    # ── Call iCargo ───────────────────────────────────────────────────────────
    with st.spinner(f"Querying iCargo for {awb_number}…"):
        try:
            client = _get_client()
            data = client.get_awb(awb_number)
            error = None
        except Exception as exc:
            data = None
            error = str(exc)

    # ── Results ───────────────────────────────────────────────────────────────
    if error:
        st.error(f"**Error:** {error}")
        st.stop()

    # Summary strip
    st.success(f"AWB **{data.get('awb', awb_number)}** retrieved successfully.")

    summary_cols = st.columns(5)
    summary_cols[0].metric("Origin", data.get("origin", "—"))
    summary_cols[1].metric("Destination", data.get("destination", "—"))
    summary_cols[2].metric("Pieces", data.get("stated_pieces", "—"))
    summary_cols[3].metric("Weight (kg)", data.get("stated_weight", "—"))
    summary_cols[4].metric("Status", data.get("status", "—"))

    st.divider()

    # Raw JSON viewer
    col_view, col_dl = st.columns([5, 1], gap="small")
    with col_view:
        st.markdown("#### Raw JSON response")
    with col_dl:
        st.download_button(
            label="⬇ Download JSON",
            data=json.dumps(data, indent=2, ensure_ascii=False),
            file_name=f"awb_{awb_number.replace('-', '')}.json",
            mime="application/json",
            use_container_width=True,
        )

    st.json(data, expanded=True)
