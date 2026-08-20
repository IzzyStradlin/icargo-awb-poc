# app/ui/pages/flight_tracking.py
"""
Flight Tracking page — real-time position and status lookup via the AirLabs
Flight Tracker API (https://airlabs.co/docs/flights), plotted on an open,
free OpenStreetMap basemap (Folium — no API key or paid map service required).
"""
from __future__ import annotations

import datetime as dt

import folium
import streamlit as st
from streamlit_folium import st_folium

from app.integration.flight_tracker_client import AirLabsClient


@st.cache_resource
def _get_client() -> AirLabsClient:
    return AirLabsClient()


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _lookup_airport(_client_key: str, iata_code: str) -> dict | None:
    """Cached best-effort airport coordinate lookup (airports rarely move)."""
    if not iata_code:
        return None
    try:
        return _get_client().get_airport(iata_code)
    except Exception:
        return None


def _normalise_flight_code(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")


def _fmt_updated(ts) -> str:
    if not ts:
        return "—"
    try:
        return dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "—"


def _build_map(flight: dict, dep_airport: dict | None, arr_airport: dict | None) -> folium.Map:
    lat, lng = flight.get("lat"), flight.get("lng")
    center = [lat, lng] if lat is not None and lng is not None else [20.0, 0.0]
    zoom = 5 if lat is not None and lng is not None else 2

    fmap = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    if lat is not None and lng is not None:
        popup = folium.Popup(
            f"<b>{flight.get('flight_iata') or flight.get('flight_icao') or '—'}</b><br>"
            f"Altitude: {flight.get('alt', '—')} m<br>"
            f"Speed: {flight.get('speed', '—')} km/h<br>"
            f"Heading: {flight.get('dir', '—')}°",
            max_width=250,
        )
        folium.Marker(
            location=[lat, lng],
            popup=popup,
            tooltip="Current position",
            icon=folium.Icon(color="darkblue", icon="plane", prefix="fa"),
        ).add_to(fmap)

    route_points = []
    if dep_airport and dep_airport.get("lat") is not None and dep_airport.get("lng") is not None:
        dep_point = [dep_airport["lat"], dep_airport["lng"]]
        folium.Marker(
            location=dep_point,
            tooltip=f"Departure: {dep_airport.get('name') or flight.get('dep_iata')}",
            icon=folium.Icon(color="green", icon="plane-departure", prefix="fa"),
        ).add_to(fmap)
        route_points.append(dep_point)

    if lat is not None and lng is not None:
        route_points.append([lat, lng])

    if arr_airport and arr_airport.get("lat") is not None and arr_airport.get("lng") is not None:
        arr_point = [arr_airport["lat"], arr_airport["lng"]]
        folium.Marker(
            location=arr_point,
            tooltip=f"Arrival: {arr_airport.get('name') or flight.get('arr_iata')}",
            icon=folium.Icon(color="red", icon="plane-arrival", prefix="fa"),
        ).add_to(fmap)
        route_points.append(arr_point)

    if len(route_points) >= 2:
        folium.PolyLine(route_points, color="#111111", weight=2, dash_array="6,8").add_to(fmap)
        fmap.fit_bounds(route_points)

    return fmap


def render_flight_tracking(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">Live operations</div>
            <h1>Flight Tracking</h1>
            <p>Enter a flight number to retrieve its real-time position and status via the AirLabs Flight Tracker API.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to Home", type="secondary"):
        on_back()
        st.stop()

    st.divider()

    for key, val in {
        "flight_track_results": None,
        "flight_track_selected": 0,
        "flight_track_error": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    col_input, col_btn = st.columns([3, 1], gap="small")
    with col_input:
        flight_input = st.text_input(
            "Flight number",
            placeholder="e.g. MS785 or FM9429 (IATA/ICAO code + number)",
            label_visibility="collapsed",
        )
    with col_btn:
        track = st.button("Track flight", type="primary", width="stretch")

    if track:
        code = _normalise_flight_code(flight_input)
        if not code:
            st.warning("Please enter a flight number.")
            st.stop()
        try:
            client = AirLabsClient()
            with st.spinner(f"Looking up {code}..."):
                results = client.get_flight(flight_iata=code)
                if not results:
                    results = client.get_flight(flight_icao=code)
            st.session_state["flight_track_results"] = results
            st.session_state["flight_track_selected"] = 0
            st.session_state["flight_track_error"] = None
        except RuntimeError as e:
            st.session_state["flight_track_results"] = None
            st.session_state["flight_track_error"] = str(e)

    if st.session_state.get("flight_track_error"):
        st.error(f"**Error:** {st.session_state['flight_track_error']}")

    results = st.session_state.get("flight_track_results")
    if results is None:
        return

    if not results:
        st.info(
            "No active flight found for this number. The AirLabs Flight Tracker API only "
            "returns flights that are currently airborne (en-route)."
        )
        return

    if len(results) > 1:
        labels = [
            f"{r.get('flight_iata') or r.get('flight_icao') or '—'} — "
            f"{r.get('dep_iata', '—')} → {r.get('arr_iata', '—')}"
            for r in results
        ]
        st.session_state["flight_track_selected"] = st.selectbox(
            f"{len(results)} matching flights found — select one",
            options=range(len(results)),
            format_func=lambda i: labels[i],
        )

    flight = results[st.session_state.get("flight_track_selected", 0) or 0]

    st.success(
        f"Flight **{flight.get('flight_iata') or flight.get('flight_icao') or '—'}** — "
        f"status: **{flight.get('status', '—')}**"
    )

    metric_cols = st.columns(5)
    metric_cols[0].metric("From", flight.get("dep_iata", "—"))
    metric_cols[1].metric("To", flight.get("arr_iata", "—"))
    metric_cols[2].metric("Altitude (m)", flight.get("alt", "—"))
    metric_cols[3].metric("Speed (km/h)", flight.get("speed", "—"))
    metric_cols[4].metric("Heading (°)", flight.get("dir", "—"))

    detail_cols = st.columns(4)
    detail_cols[0].caption(f"Airline: **{flight.get('airline_iata') or flight.get('airline_icao') or '—'}**")
    detail_cols[1].caption(f"Aircraft: **{flight.get('aircraft_icao', '—')}**")
    detail_cols[2].caption(f"Registration: **{flight.get('reg_number', '—')}**")
    detail_cols[3].caption(f"Last update: **{_fmt_updated(flight.get('updated'))}**")

    st.divider()

    dep_airport = _lookup_airport("airlabs", flight.get("dep_iata", "")) if flight.get("dep_iata") else None
    arr_airport = _lookup_airport("airlabs", flight.get("arr_iata", "")) if flight.get("arr_iata") else None

    fmap = _build_map(flight, dep_airport, arr_airport)
    st_folium(fmap, width=None, height=440, returned_objects=[])

    with st.expander("Raw AirLabs response", expanded=False):
        st.json(flight, expanded=True)
