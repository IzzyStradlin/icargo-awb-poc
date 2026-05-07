# app/integration/awb_repository.py
from typing import Optional, Dict, Any
from .icargo_ibs_client import ICargoIBSClient

class AwbRepository:
    """
    Exposes AWB-specific operations.
    API path is a PoC placeholder: adapt to the real iCargo paths.
    """

    def __init__(self, client: Optional[ICargoIBSClient] = None):
        self.client = client or ICargoIBSClient()

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