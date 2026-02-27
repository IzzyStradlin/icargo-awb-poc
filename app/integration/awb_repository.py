# app/integration/awb_repository.py
from typing import Optional, Dict, Any
from .icargo_client import ICargoClient

class AwbRepository:
    """
    Espone operazioni specifiche su AWB.
    L'API path è un placeholder PoC: adattare ai path iCargo reali.
    """

    def __init__(self, client: Optional[ICargoClient] = None):
        self.client = client or ICargoClient()

    def get_awb(self, awb_prefix: str, awb_serial: str) -> Dict[str, Any]:
        path = f"awb/{awb_prefix}/{awb_serial}"
        resp = self.client.get(path)
        resp.raise_for_status()
        return resp.json()

    def update_awb(self, awb_prefix: str, awb_serial: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = f"awb/{awb_prefix}/{awb_serial}"
        resp = self.client.patch(path, json=payload)
        resp.raise_for_status()
        return resp.json()