# app/interpretation/awb_normalizer.py
from .awb_schema import AwbData

class AwbNormalizer:
    """Normalizza e valida i campi AWB (formati base per PoC)."""

    def normalize(self, data: AwbData) -> AwbData:
        if data.origin:
            data.origin = data.origin.strip().upper()[:3]
        if data.destination:
            data.destination = data.destination.strip().upper()[:3]
        if data.awb_prefix:
            data.awb_prefix = data.awb_prefix.strip()[:3]
        if data.awb_serial:
            data.awb_serial = "".join(filter(str.isdigit, data.awb_serial))[:8]
        return data