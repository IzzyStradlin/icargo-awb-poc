# app/compare/awb_diff_ibs.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List


# -----------------------------
# Normalizers / helpers
# -----------------------------
def _norm_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    s = re.sub(r"\s+", " ", s)
    return s if s else None


def _norm_airport(x: Any) -> Optional[str]:
    s = _norm_str(x)
    return s.upper() if s else None


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    """Return first non-empty value among candidate keys."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d.get(k) not in (None, "", []):
            return d.get(k)
    return None


def _get_nested(d: Dict[str, Any], path: str) -> Any:
    """Simple dotted-path getter for dicts only."""
    cur: Any = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _num_from_any(x: Any) -> Optional[float]:
    """
    Accepts:
      - 150 / 150.0
      - "150 kg", "150.0KG", "150,5"
      - {"value":150,"unit":"kg"} or {"amount":150}
    Returns float or None.
    """
    if x is None:
        return None

    if isinstance(x, (int, float)):
        return float(x)

    if isinstance(x, dict):
        v = x.get("value") if "value" in x else x.get("amount")
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            x = v
        else:
            return None

    if isinstance(x, str):
        # Extract first numeric occurrence.
        m = re.search(r"(-?\d+(?:\.\d+)?)", x.replace(",", "."))
        return float(m.group(1)) if m else None

    return None


def _int_from_any(x: Any) -> Optional[int]:
    n = _num_from_any(x)
    return int(n) if n is not None else None


def _float_equal(a: Optional[float], b: Optional[float], tol: float = 0.01) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


# -----------------------------
# Mapping: LLM output (PDF -> Cohere JSON)
# We assume Cohere returns EXACT keys:
# awb_number, origin, destination, agent, pieces, weight, goods_description,
# shipper, consignee, flight_number, flight_date
# -----------------------------
def map_extracted_awb_llm(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize LLM output into a flat dict for comparison.
    Even if Cohere should return exact keys, we still normalize types.
    """
    out: Dict[str, Any] = {}

    out["awb_number"] = _norm_str(_pick(extracted, "awb_number", "awb", "awbNumber"))
    out["origin"] = _norm_airport(_pick(extracted, "origin", "originAirport", "origin_airport"))
    out["destination"] = _norm_airport(_pick(extracted, "destination", "destinationAirport", "destination_airport"))

    # agent could be string or dict in edge cases
    agent_val = _pick(extracted, "agent", "agent_name", "agentName")
    if isinstance(agent_val, dict):
        agent_val = agent_val.get("name") or agent_val.get("agentName") or agent_val.get("agent_name")
    out["agent"] = _norm_str(agent_val)

    out["pieces"] = _int_from_any(_pick(extracted, "pieces", "stated_pieces", "statedPieces"))
    out["weight"] = _num_from_any(_pick(extracted, "weight", "stated_weight", "statedWeight"))

    out["goods_description"] = _norm_str(_pick(
        extracted,
        "goods_description", "goodsDescription",
        "shipment_description", "shipmentDescription"
    ))

    shipper_val = _pick(extracted, "shipper", "shipper_name", "shipperName")
    if isinstance(shipper_val, dict):
        shipper_val = shipper_val.get("name") or shipper_val.get("shipperName") or shipper_val.get("shipper_name")
    out["shipper"] = _norm_str(shipper_val)

    consignee_val = _pick(extracted, "consignee", "consignee_name", "consigneeName")
    if isinstance(consignee_val, dict):
        consignee_val = consignee_val.get("name") or consignee_val.get("consigneeName") or consignee_val.get("consignee_name")
    out["consignee"] = _norm_str(consignee_val)

    out["flight_number"] = _norm_str(_pick(extracted, "flight_number", "flightNumber", "flight_no", "flightNo"))
    out["flight_date"] = _norm_str(_pick(extracted, "flight_date", "flightDate"))

    return out


# -----------------------------
# Mapping: iCargo IBS AWB JSON (GET /enterprise/v2/awbs/{awb})
# Best-effort: tries common snake_case/camelCase and nested objects.
# -----------------------------
def map_icargo_awb_ibs(icargo_awb: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def pick(*keys: str) -> Any:
        return _pick(icargo_awb, *keys)

    out["awb_number"] = _norm_str(pick("awb", "awb_number", "awbNumber", "airwaybillNumber"))
    out["origin"] = _norm_airport(pick("origin", "originAirport", "origin_airport"))
    out["destination"] = _norm_airport(pick("destination", "destinationAirport", "destination_airport"))

    # agent (string or object)
    agent_val = pick("agent", "agentName", "agent_name")
    if agent_val is None:
        agent_val = _get_nested(icargo_awb, "agent.name") or _get_nested(icargo_awb, "agent.agentName")
    out["agent"] = _norm_str(agent_val)

    out["pieces"] = _int_from_any(pick("stated_pieces", "statedPieces", "pieces", "pieceCount"))
    out["weight"] = _num_from_any(pick("stated_weight", "statedWeight", "weight", "grossWeight"))

    out["goods_description"] = _norm_str(
        pick("shipment_description", "shipmentDescription", "goods_description", "goodsDescription")
    )

    out["shipper"] = _norm_str(
        _get_nested(icargo_awb, "shipper.name")
        or _get_nested(icargo_awb, "shipper.shipperName")
        or pick("shipper_name", "shipperName")
    )

    out["consignee"] = _norm_str(
        _get_nested(icargo_awb, "consignee.name")
        or _get_nested(icargo_awb, "consignee.consigneeName")
        or pick("consignee_name", "consigneeName")
    )

    # flight: may be in requested_flight/requestedFlight[0]
    rf = icargo_awb.get("requested_flight") or icargo_awb.get("requestedFlight") or []
    if isinstance(rf, list) and rf and isinstance(rf[0], dict):
        carrier = _norm_str(rf[0].get("carrier_code") or rf[0].get("carrierCode")) or ""
        fnum = _norm_str(rf[0].get("flight_number") or rf[0].get("flightNumber")) or ""
        out["flight_number"] = f"{carrier}{fnum}" if (carrier or fnum) else None
        out["flight_date"] = _norm_str(rf[0].get("flight_date") or rf[0].get("flightDate"))
    else:
        out["flight_number"] = _norm_str(pick("flight_number", "flightNumber", "flightNo", "flight_no"))
        out["flight_date"] = _norm_str(pick("flight_date", "flightDate"))

    return out


# -----------------------------
# Diff
# -----------------------------
def diff_awb(extracted_flat: Dict[str, Any], icargo_flat: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = [
        "awb_number",
        "origin",
        "destination",
        "agent",
        "pieces",
        "weight",
        "goods_description",
        "shipper",
        "consignee",
        "flight_number",
        "flight_date",
    ]

    rows: List[Dict[str, Any]] = []
    for f in fields:
        a = extracted_flat.get(f)
        b = icargo_flat.get(f)
        match = _float_equal(a, b, tol=0.01) if f == "weight" else (a == b)
        rows.append({
            "field": f,
            "pdf_llm": str(a) if a is not None else None,  # Converti a stringa per Arrow compatibility
            "icargo": str(b) if b is not None else None,   # Converti a stringa per Arrow compatibility
            "match": match
        })

    return rows