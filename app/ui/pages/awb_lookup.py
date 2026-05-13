"""
AWB Lookup page — retrieve a MAWB record and its linked House AWBs from iCargo IBS.
"""
import json
import streamlit as st

from app.integration.icargo_ibs_client import ICargoIBSClient


@st.cache_resource
def _get_client() -> ICargoIBSClient:
    return ICargoIBSClient()


def _normalise_awb(awb_raw: str) -> str:
    digits_only = awb_raw.replace("-", "").replace(" ", "")
    if digits_only.isdigit() and len(digits_only) == 11:
        return f"{digits_only[:3]}-{digits_only[3:]}"
    return awb_raw


def render_awb_lookup(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">iCargo IBS — live query</div>
            <h1>AWB Lookup</h1>
            <p>Enter an AWB number to retrieve the MAWB record and its linked House AWBs from iCargo.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Home"):
        on_back()
        st.stop()

    st.divider()

    # ── Session state ─────────────────────────────────────────────────────────
    for key, val in {
        "lookup_awb_number": None,
        "lookup_mawb_data": None,
        "lookup_hawbs_data": None,
        "lookup_hawbs_error": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # ── Input form ────────────────────────────────────────────────────────────
    col_input, col_btn = st.columns([3, 1], gap="small")
    with col_input:
        awb_input = st.text_input(
            "AWB number",
            placeholder="233-10448211",
            label_visibility="collapsed",
        )
    with col_btn:
        search = st.button("🔍 Retrieve", width='stretch')

    if search:
        awb_raw = awb_input.strip()
        if not awb_raw:
            st.warning("Please enter an AWB number.")
            st.stop()
        awb_number = _normalise_awb(awb_raw)
        with st.spinner(f"Querying iCargo for {awb_number}…"):
            try:
                client = _get_client()
                data = client.get_awb(awb_number)
                st.session_state["lookup_awb_number"] = awb_number
                st.session_state["lookup_mawb_data"] = data
                st.session_state["lookup_hawbs_data"] = None
                st.session_state["lookup_hawbs_error"] = None
            except Exception as exc:
                st.error(f"**Error:** {exc}")
                st.stop()

    if not st.session_state.get("lookup_mawb_data"):
        st.stop()

    data = st.session_state["lookup_mawb_data"]
    awb_number = st.session_state["lookup_awb_number"]

    # ── Summary strip ─────────────────────────────────────────────────────────
    st.success(f"AWB **{data.get('awb', awb_number)}** retrieved successfully.")
    summary_cols = st.columns(5)
    summary_cols[0].metric("Origin", data.get("origin", "—"))
    summary_cols[1].metric("Destination", data.get("destination", "—"))
    summary_cols[2].metric("Pieces", data.get("stated_pieces", "—"))
    summary_cols[3].metric("Weight (kg)", data.get("stated_weight", "—"))
    summary_cols[4].metric("Status", data.get("status", "—"))

    st.divider()

    # ── Tabs: MAWB / Linked HAWBs ─────────────────────────────────────────────
    tab_mawb, tab_hawbs = st.tabs(["📋 MAWB", "🏠 Linked HAWBs"])

    with tab_mawb:
        col_view, col_dl = st.columns([5, 1], gap="small")
        with col_view:
            st.markdown("#### Raw JSON response")
        with col_dl:
            st.download_button(
                label="⬇ Download JSON",
                data=json.dumps(data, indent=2, ensure_ascii=False),
                file_name=f"awb_{awb_number.replace('-', '')}.json",
                mime="application/json",
                width='stretch',
                key="dl_mawb",
            )
        st.json(data, expanded=True)

    with tab_hawbs:
        st.caption("Calls `GET /v2/awbs/{awb}/hawbs` to retrieve all House AWBs linked to this MAWB.")
        if st.button("🔍 Fetch linked HAWBs", key="fetch_hawbs_btn"):
            with st.spinner(f"Querying HAWBs for MAWB {awb_number}…"):
                try:
                    client = _get_client()
                    hawbs_resp = client.get_hawbs(awb_number)
                    st.session_state["lookup_hawbs_data"] = hawbs_resp
                    st.session_state["lookup_hawbs_error"] = None
                except Exception as exc:
                    st.session_state["lookup_hawbs_data"] = None
                    st.session_state["lookup_hawbs_error"] = str(exc)

        if st.session_state.get("lookup_hawbs_error"):
            st.error(f"**Error:** {st.session_state['lookup_hawbs_error']}")

        hawbs_resp = st.session_state.get("lookup_hawbs_data")
        if hawbs_resp is not None:
            # Normalise to list
            if isinstance(hawbs_resp, list):
                hawb_list = hawbs_resp
            elif isinstance(hawbs_resp, dict):
                hawb_list = (
                    hawbs_resp.get("hawbs")
                    or hawbs_resp.get("body")
                    or hawbs_resp.get("data")
                    or [hawbs_resp]
                )
            else:
                hawb_list = []

            if hawb_list:
                st.success(f"**{len(hawb_list)} HAWB(s)** linked to MAWB {awb_number}.")
                _, col_dl2 = st.columns([5, 1], gap="small")
                with col_dl2:
                    st.download_button(
                        label="⬇ Download JSON",
                        data=json.dumps(hawbs_resp, indent=2, ensure_ascii=False),
                        file_name=f"hawbs_{awb_number.replace('-', '')}.json",
                        mime="application/json",
                        width='stretch',
                        key="dl_hawbs",
                    )
                for i, hawb in enumerate(hawb_list):
                    hawb_num = (
                        hawb.get("hawb_number")
                        or hawb.get("hawbNumber")
                        or hawb.get("houseAirwaybillNumber")
                        or f"HAWB_{i + 1}"
                    )
                    with st.expander(f"📜 {hawb_num}", expanded=(i == 0)):
                        st.json(hawb, expanded=True)
            else:
                st.info("No HAWBs found for this MAWB (empty response).")
                st.json(hawbs_resp, expanded=True)
