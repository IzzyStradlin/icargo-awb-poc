# app/comparison/awb_diff_engine.py
from typing import Dict, Any, List, TypedDict

class DiffItem(TypedDict):
    field: str
    source_value: Any
    system_value: Any
    match: bool

class AwbDiffEngine:
    """Confronta i campi estratti dal documento con quelli iCargo."""

    def diff(self, extracted: Dict[str, Any], system: Dict[str, Any]) -> List[DiffItem]:
        fields = [
            "awb_prefix", "awb_serial", "shipper", "consignee",
            "origin", "destination", "pieces", "weight",
            "goods_description", "flight_no", "flight_date",
        ]
        out: List[DiffItem] = []
        for f in fields:
            out.append({
                "field": f,
                "source_value": extracted.get(f),
                "system_value": system.get(f),
                "match": extracted.get(f) == system.get(f),
            })
        return out
``