# app/integration/flight_tracker_client.py
"""Client for the AirLabs Flight Tracker API (real-time flights + airport lookup).

Docs: https://airlabs.co/docs/flights
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()


class AirLabsClient:
    BASE_URL = "https://airlabs.co/api/v9"

    def __init__(self):
        self.api_key = os.getenv("AIRLABS_API_KEY")
        self.timeout = float(os.getenv("AIRLABS_TIMEOUT", "15"))
        if not self.api_key:
            raise RuntimeError("AIRLABS_API_KEY missing in .env")

    def _get(self, endpoint: str, params: dict) -> list[dict]:
        params = {**params, "api_key": self.api_key}
        url = f"{self.BASE_URL}/{endpoint}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

        if isinstance(data, dict) and data.get("error"):
            message = data["error"].get("message") or str(data["error"])
            raise RuntimeError(f"AirLabs API error: {message}")

        response = data.get("response") if isinstance(data, dict) else data
        return response if isinstance(response, list) else []

    def get_flight(self, flight_iata: Optional[str] = None, flight_icao: Optional[str] = None) -> list[dict]:
        """Real-time position/status for a flight currently tracked (en-route)."""
        if flight_iata:
            params = {"flight_iata": flight_iata.upper()}
        elif flight_icao:
            params = {"flight_icao": flight_icao.upper()}
        else:
            raise ValueError("flight_iata or flight_icao is required")
        return self._get("flights", params)

    def get_flight_by_registration(self, reg_number: str) -> list[dict]:
        """Real-time position/status looked up by aircraft tail/registration number.

        Useful when a flight/callsign lookup misses (e.g. cargo charters that fly
        under a different callsign than their commercial flight number).
        """
        if not reg_number:
            raise ValueError("reg_number is required")
        return self._get("flights", {"reg_number": reg_number.strip().upper()})

    def get_airport(self, iata_code: str) -> Optional[dict]:
        """Best-effort airport lookup (coordinates, name) by IATA code."""
        results = self._get("airports", {"iata_code": iata_code.upper()})
        return results[0] if results else None
