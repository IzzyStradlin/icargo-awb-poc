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
    out["chargeable_weight"] = _num_from_any(_pick(extracted, "chargeable_weight", "chargeableWeight"))
    out["rate"] = _num_from_any(_pick(extracted, "rate", "rate_charge", "rateCharge"))
    out["total_charge"] = _num_from_any(_pick(extracted, "total_charge", "totalCharge", "total"))

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
    out["chargeable_weight"] = _num_from_any(pick("chargeable_weight", "chargeableWeight", "chargeableWt"))
    out["rate"] = _num_from_any(pick("rate", "rate_charge", "rateCharge", "ratePerKg"))
    out["total_charge"] = _num_from_any(pick("total_charge", "totalCharge", "total", "totalCharges"))

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
        "chargeable_weight",
        "rate",
        "total_charge",
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
        if f in ("weight", "chargeable_weight", "rate", "total_charge"):
            match = _float_equal(a, b, tol=0.01)
        else:
            match = (a == b)
        rows.append({
            "field": f,
            "pdf_llm": str(a) if a is not None else None,  # Convert to string for Arrow compatibility
            "icargo": str(b) if b is not None else None,   # Convert to string for Arrow compatibility
            "match": match
        })

    return rows


# -----------------------------
# Mapping: iCargo IBS HAWB JSON (GET /enterprise/v2/awbs/{mawb}/hawbs)
# -----------------------------
def map_icargo_hawb_ibs(icargo_hawb: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def pick(*keys: str) -> Any:
        return _pick(icargo_hawb, *keys)

    out["hawb_number"] = _norm_str(pick("hawb", "hawb_number", "hawbNumber", "houseAirwaybillNumber"))
    out["origin"] = _norm_airport(pick("origin", "originAirport", "origin_airport"))
    out["destination"] = _norm_airport(pick("destination", "destinationAirport", "destination_airport"))

    out["pieces"] = _int_from_any(pick("stated_pieces", "statedPieces", "pieces", "pieceCount"))
    out["weight"] = _num_from_any(pick("stated_weight", "statedWeight", "weight", "grossWeight"))
    out["chargeable_weight"] = _num_from_any(pick("chargeable_weight", "chargeableWeight", "chargeableWt"))
    out["volume"] = _num_from_any(pick("volume", "volumetricWeight", "volumeWeight"))
    out["total_charge"] = _num_from_any(pick("total_charge", "totalCharge", "total", "totalCharges"))

    out["goods_description"] = _norm_str(
        pick("shipment_description", "shipmentDescription", "goods_description", "goodsDescription")
    )

    out["shipper"] = _norm_str(
        _get_nested(icargo_hawb, "shipper.name")
        or _get_nested(icargo_hawb, "shipper.shipperName")
        or pick("shipper_name", "shipperName")
    )
    out["consignee"] = _norm_str(
        _get_nested(icargo_hawb, "consignee.name")
        or _get_nested(icargo_hawb, "consignee.consigneeName")
        or pick("consignee_name", "consigneeName")
    )
    out["notify_party"] = _norm_str(
        _get_nested(icargo_hawb, "notify_party.name")
        or _get_nested(icargo_hawb, "notifyParty.name")
        or pick("notify_party", "notifyParty")
    )

    # flight: may be in requested_flight/requestedFlight[0]
    rf = icargo_hawb.get("requested_flight") or icargo_hawb.get("requestedFlight") or []
    if isinstance(rf, list) and rf and isinstance(rf[0], dict):
        carrier = _norm_str(rf[0].get("carrier_code") or rf[0].get("carrierCode")) or ""
        fnum = _norm_str(rf[0].get("flight_number") or rf[0].get("flightNumber")) or ""
        out["flight_number"] = f"{carrier}{fnum}" if (carrier or fnum) else None
        out["flight_date"] = _norm_str(rf[0].get("flight_date") or rf[0].get("flightDate"))
    else:
        out["flight_number"] = _norm_str(pick("flight_number", "flightNumber", "flightNo", "flight_no"))
        out["flight_date"] = _norm_str(pick("flight_date", "flightDate"))

    out["hs_code"] = _norm_str(pick("hs_code", "hsCode", "commodityCode", "harmonizedCode"))
    out["special_handling"] = _norm_str(pick("special_handling", "specialHandling", "specialHandlingCode"))
    out["declared_value_carriage"] = _norm_str(pick(
        "declared_value_carriage", "declaredValueCarriage", "dvcAmount", "declaredValue"
    ))
    out["declared_value_customs"] = _norm_str(pick(
        "declared_value_customs", "declaredValueCustoms", "dvcCustomsAmount"
    ))

    return out


def diff_hawb(extracted_hawb: Dict[str, Any], icargo_flat: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = [
        "hawb_number",
        "origin",
        "destination",
        "shipper",
        "consignee",
        "notify_party",
        "pieces",
        "weight",
        "chargeable_weight",
        "volume",
        "total_charge",
        "goods_description",
        "flight_number",
        "flight_date",
        "hs_code",
        "special_handling",
        "declared_value_carriage",
        "declared_value_customs",
    ]

    rows: List[Dict[str, Any]] = []
    for f in fields:
        a = extracted_hawb.get(f)
        b = icargo_flat.get(f)
        if f in ("weight", "chargeable_weight", "volume", "total_charge"):
            match = _float_equal(
                _num_from_any(a) if not isinstance(a, float) else a,
                b,
                tol=0.01,
            )
        else:
            match = (a == b)
        rows.append({
            "field": f,
            "pdf_llm": str(a) if a is not None else None,
            "icargo": str(b) if b is not None else None,
            "match": match,
        })

    return rows