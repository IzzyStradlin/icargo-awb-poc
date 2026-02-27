# app/integration/icargo_ibs_client.py
from __future__ import annotations

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

class ICargoIBSClient:
    def __init__(self):
        self.base_url = (os.getenv("ICARGO_BASE_URL") or "").rstrip("/")
        self.username = os.getenv("ICARGO_USERNAME")
        self.password = os.getenv("ICARGO_PASSWORD")
        self.token = None
        self.timeout = float(os.getenv("ICARGO_TIMEOUT", "15"))

        if not self.base_url:
            raise RuntimeError("ICARGO_BASE_URL mancante in .env")
        if not self.username or not self.password:
            raise RuntimeError("ICARGO_USERNAME / ICARGO_PASSWORD mancanti in .env")

    def authenticate(self) -> str:
        url = f"{self.base_url}/auth/m4/private/v1/authenticate"
        payload = {"username": self.username, "password": self.password}
        headers = {"Content-Type": "application/json", "Accept": "*/*"}

        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        # struttura: data["body"]["security"]["id_token"]
        token = data["body"]["security"]["id_token"]
        self.token = token
        return token

    def _headers(self) -> dict:
        if not self.token:
            self.authenticate()
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def get_awb(self, awb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{awb_code}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()

    def get_booking(self, awb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v1/bookings/awbs/{awb_code}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()

    def get_tracking(self, awb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v1/trackings/awbs/{awb_code}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()