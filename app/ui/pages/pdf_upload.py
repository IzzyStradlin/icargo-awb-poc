# app/ui/pages/pdf_upload.py
"""
PDF → Claude Vision → AWB extraction.
Flow: upload PDF → auto-split by MAWB → Claude Vision per document → results.
No OCR step exposed to user. No Cohere. No regex parsing.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv, set_key

from app.extraction.pdf_text_extractor import PDFTextExtractor
from app.extraction.awb_document_presplitter import AwbDocumentPreSplitter
from app.interpretation.awb_vision_extractor import AwbVisionExtractor
from app.compare.awb_diff_ibs import map_icargo_awb_ibs, diff_awb, map_icargo_hawb_ibs, diff_hawb
from app.ui.assets.branding import get_colors, get_brand_info

load_dotenv()

logger = logging.getLogger(__name__)


# ── Cached Vision extractor ────────────────────────────────────────────────
@st.cache_resource
def get_vision_extractor(
    provider_name: str = "claude",
    png_folder: Optional[str] = None,
    json_folder: Optional[str] = None,
    group_label: Optional[str] = None,
) -> AwbVisionExtractor:
    return AwbVisionExtractor(
        provider_name=provider_name,
        png_folder=png_folder,
        json_folder=json_folder,
        group_label=group_label,
    )


def _persist_msc_tech_env(key: str, value: str) -> None:
    """Persist MSC Tech AI environment variables to .env (best effort)."""
    try:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        set_key(str(env_path), key, value)
    except (PermissionError, OSError) as e:
        # If .env is locked (by Streamlit or OneDrive), just set in memory
        # This allows the app to continue running even if file persistence fails
        logger.warning(f"Failed to persist {key} to .env: {e} — using in-memory only")
    finally:
        # Always set in memory so the value is available for this session
        os.environ[key] = value


# ── iCargo IBS client ──────────────────────────────────────────────────────
class ICargoIBSClient:
    def __init__(self):
        self.base_url = (os.getenv("ICARGO_BASE_URL") or "https://mac-stag-icargo.ibsplc.aero").rstrip("/")
        self.username = os.getenv("ICARGO_USERNAME")
        self.password = os.getenv("ICARGO_PASSWORD")
        self.timeout = float(os.getenv("ICARGO_TIMEOUT", "15"))
        self.token = None
        if not self.username or not self.password:
            raise RuntimeError("ICARGO_USERNAME / ICARGO_PASSWORD missing in .env")

    def _ensure_preprod_write(self):
        # Hard safety guard: write operations are allowed only on preprod stage.
        allowed_host = "https://mac-stag-icargo.ibsplc.aero"
        if not self.base_url.lower().startswith(allowed_host):
            raise RuntimeError(
                "Write blocked: iCargo update is allowed only on preprod stage "
                f"({allowed_host}). Current base URL: {self.base_url}"
            )

    def authenticate(self):
        url = f"{self.base_url}/auth/m4/private/v1/authenticate"
        r = requests.post(
            url,
            json={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Auth error: {r.status_code} {r.text}")
        self.token = r.json()["body"]["security"]["id_token"]

    def _headers(self):
        if not self.token:
            self.authenticate()
        # Prod-like behavior: Authorization Bearer is the primary working mode.
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _auth_header_variants(self) -> list[dict]:
        if not self.token:
            self.authenticate()
        token = self.token or ""
        return [
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            {
                "ICO-Authorization": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        ]

    def _request(self, method: str, url: str, json_body=None):
        """Execute an iCargo HTTP call with one automatic token refresh retry.

        If the token is expired (401 invalid_token), refresh and retry once.
        """
        with requests.Session() as session:
            # First attempt with default header set.
            r = session.request(method, url, json=json_body, headers=self._headers(), timeout=self.timeout)
            if r.status_code != 401:
                return r

            # On any 401, force token refresh and retry with header variants.
            self.token = None
            self.authenticate()

            last_response = r
            for headers in self._auth_header_variants():
                last_response = session.request(method, url, json=json_body, headers=headers, timeout=self.timeout)
                if last_response.status_code != 401:
                    return last_response

            return last_response

    def get_awb(self, awb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{awb_code}"
        r = self._request("GET", url)
        if r.status_code != 200:
            raise RuntimeError(f"Error GET AWB: {r.status_code} {r.text}")
        return r.json()

    def get_hawbs(self, mawb_code: str) -> dict:
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{mawb_code}/hawbs"
        r = self._request("GET", url)
        if r.status_code != 200:
            raise RuntimeError(f"Error GET HAWBs: {r.status_code} {r.text}")
        return r.json()

    def save_awb(self, awb_code: str, payload: dict) -> str:
        self._ensure_preprod_write()
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{awb_code}"
        logger.info("POST AWB %s payload: %s", awb_code, json.dumps(payload, default=str))
        r = self._request("POST", url, json_body=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Error POST AWB: {r.status_code} {r.text}")
        return r.text or "AWB data updated successfully"

    def save_hawbs(self, awb_code: str, payload: list[dict]) -> str:
        self._ensure_preprod_write()
        url = f"{self.base_url}/icargo-api/m4/enterprise/v2/awbs/{awb_code}/hawbs"
        # Confirmed via the real Swagger spec: the endpoint expects a JSON array body
        # (our earlier per-object-without-array theory was wrong).
        logger.info("POST HAWBs %s payload: %s", awb_code, json.dumps(payload, default=str))
        r = self._request("POST", url, json_body=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Error POST HAWBs: {r.status_code} {r.text}")
        return r.text or "HAWB data updated successfully"


# ── AWB form renderer ──────────────────────────────────────────────────────
def _val(v, suffix="") -> str:
    return f"{v}{suffix}" if v not in (None, "", "null") else "—"


def _fmt_addr(data: dict, prefix: str) -> str:
    parts = [
        data.get(f"{prefix}_street"),
        data.get(f"{prefix}_city"),
        data.get(f"{prefix}_province"),
        data.get(f"{prefix}_zip"),
        data.get(f"{prefix}_country"),
    ]
    return ", ".join(p for p in parts if p) or "—"


def _normalise_awb(awb_raw: str) -> str:
    """Normalize AWB to XXX-XXXXXXXX when 11 digits are provided."""
    digits_only = re.sub(r"\D", "", (awb_raw or ""))
    if digits_only.isdigit() and len(digits_only) == 11:
        return f"{digits_only[:3]}-{digits_only[3:]}"
    return (awb_raw or "").strip()


def _resolve_awb_for_icargo(awb_num: str, mawb_data: dict | None = None) -> str:
    """Resolve a usable AWB for iCargo from multiple possible sources."""
    candidates: list[str] = []

    if awb_num:
        candidates.append(str(awb_num))

    if isinstance(mawb_data, dict):
        awb_field = mawb_data.get("awb_number")
        if awb_field:
            candidates.append(str(awb_field))

        prefix = str(mawb_data.get("awb_prefix") or "").strip()
        serial = str(mawb_data.get("awb_serial") or "").strip()
        prefix_digits = re.sub(r"\D", "", prefix)
        serial_digits = re.sub(r"\D", "", serial)
        if len(prefix_digits) == 3 and len(serial_digits) == 8:
            candidates.append(f"{prefix_digits}{serial_digits}")

    for candidate in candidates:
        normalized = _normalise_awb(candidate)
        if normalized and re.fullmatch(r"\d{3}-\d{8}", normalized):
            return normalized

    return ""


def _to_records(table_like) -> list[dict]:
    if table_like is None:
        return []
    if isinstance(table_like, list):
        return [r for r in table_like if isinstance(r, dict)]
    if hasattr(table_like, "to_dict"):
        try:
            return table_like.to_dict("records")
        except Exception:
            return []
    return []


def _selected_fields_from_rows(rows: list[dict]) -> set[str]:
    selected: set[str] = set()
    for row in rows:
        if bool(row.get("apply")):
            field = str(row.get("field") or "").strip()
            if field:
                selected.add(field)
    return selected


def _edited_pdf_values_from_rows(rows: list[dict]) -> dict[str, object]:
    edited: dict[str, object] = {}
    for row in rows:
        if not bool(row.get("apply")):
            continue
        field = str(row.get("field") or "").strip()
        if not field:
            continue
        edited[field] = row.get("pdf_llm")
    return edited


def _to_int(value) -> Optional[int]:
    if value in (None, "", "—"):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", ".")
        return int(float(value))
    except Exception:
        return None


def _to_float(value) -> Optional[float]:
    if value in (None, "", "—"):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", ".")
        return float(value)
    except Exception:
        return None


def _coalesce_value(field: str, edited_values: dict[str, object], extracted_values: dict) -> object:
    if field in edited_values:
        value = edited_values.get(field)
        # A blanked-out editor cell should fall back to the original value,
        # not silently become 0/empty (e.g. pieces=0 sent instead of skipping the edit).
        if value not in (None, "", "—"):
            return value
    return extracted_values.get(field)


MAWB_POST_EDITABLE_FIELDS = [
    "origin",
    "destination",
    "pieces",
    "weight",
    "chargeable_weight",
    "volume",
    "goods_description",
    "currency",
    "rate",
    "total_charge",
    "declared_value_carriage",
    "declared_value_customs",
    "shipper",
    "consignee",
    "agent",
    "notify_party",
    "flight_number",
    "flight_date",
    "hs_code",
    "special_handling",
    "unit_weight",
    "unit_volume",
    "unit_length",
    "nature_of_goods",
    "commodity",
]


HAWB_POST_EDITABLE_FIELDS = [
    "hawb_number",
    "origin",
    "destination",
    "pieces",
    "weight",
    "chargeable_weight",
    "volume",
    "goods_description",
    "rate",
    "total_charge",
    "declared_value_carriage",
    "declared_value_customs",
    "shipper",
    "consignee",
    "notify_party",
    "flight_number",
    "flight_date",
    "hs_code",
    "special_handling",
    "dimensions",
]


def _to_editor_cell(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _augment_rows_with_post_fields(rows: list[dict], source_data: dict, post_fields: list[str]) -> list[dict]:
    out: list[dict] = [dict(r) for r in rows if isinstance(r, dict)]
    existing_fields = {str(r.get("field") or "").strip() for r in out}

    for field in post_fields:
        if field in existing_fields:
            continue
        out.append({
            "field": field,
            "pdf_llm": _to_editor_cell((source_data or {}).get(field)),
            "icargo": None,
            "match": True,
            "_extra_post_field": True,
        })

    return out


def _editor_rows_with_apply(rows: list[dict], default_apply_mismatch: bool = True) -> list[dict]:
    editor_rows: list[dict] = []
    for row in rows:
        is_extra = bool(row.get("_extra_post_field"))
        cleaned = {k: v for k, v in row.items() if k != "_extra_post_field"}
        cleaned["apply"] = False if is_extra else (default_apply_mismatch and (not bool(cleaned.get("match"))))
        editor_rows.append(cleaned)
    return editor_rows


def _empty_placeholder_uld_sections(value):
    """Replace ULD sections containing only empty or zero values with empty collections."""
    if isinstance(value, list):
        return [_empty_placeholder_uld_sections(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {
        key: _empty_placeholder_uld_sections(item)
        for key, item in value.items()
    }
    for key, item in normalized.items():
        key_name = "".join(character for character in str(key).lower() if character.isalnum())
        if key_name.startswith("uld") and not _has_uld_content(item):
            normalized[key] = [] if isinstance(item, list) else {}
    return normalized


def _has_uld_content(value) -> bool:
    if isinstance(value, dict):
        return any(_has_uld_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_uld_content(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() != "0"
    return value not in (None, 0, False)


def _build_awb_update_payload(
    base_awb: dict,
    extracted_mawb: dict,
    selected_fields: set[str],
    edited_values: dict[str, object],
    awb_code: str,
) -> dict:
    payload = dict(base_awb or {})
    payload["awb"] = awb_code

    def _ensure(path_root: str) -> dict:
        obj = payload.get(path_root)
        if not isinstance(obj, dict):
            obj = {}
            payload[path_root] = obj
        return obj

    origin_v = _coalesce_value("origin", edited_values, extracted_mawb)
    destination_v = _coalesce_value("destination", edited_values, extracted_mawb)
    pieces_v = _coalesce_value("pieces", edited_values, extracted_mawb)
    weight_v = _coalesce_value("weight", edited_values, extracted_mawb)
    chargeable_weight_v = _coalesce_value("chargeable_weight", edited_values, extracted_mawb)
    volume_v = _coalesce_value("volume", edited_values, extracted_mawb)
    goods_v = _coalesce_value("goods_description", edited_values, extracted_mawb)
    currency_v = _coalesce_value("currency", edited_values, extracted_mawb)
    rate_v = _coalesce_value("rate", edited_values, extracted_mawb)
    total_charge_v = _coalesce_value("total_charge", edited_values, extracted_mawb)
    declared_value_carriage_v = _coalesce_value("declared_value_carriage", edited_values, extracted_mawb)
    declared_value_customs_v = _coalesce_value("declared_value_customs", edited_values, extracted_mawb)
    shipper_v = _coalesce_value("shipper", edited_values, extracted_mawb)
    consignee_v = _coalesce_value("consignee", edited_values, extracted_mawb)
    agent_v = _coalesce_value("agent", edited_values, extracted_mawb)
    notify_party_v = _coalesce_value("notify_party", edited_values, extracted_mawb)
    flight_date_v = _coalesce_value("flight_date", edited_values, extracted_mawb)
    flight_num_v = _coalesce_value("flight_number", edited_values, extracted_mawb)
    hs_code_v = _coalesce_value("hs_code", edited_values, extracted_mawb)
    special_handling_v = _coalesce_value("special_handling", edited_values, extracted_mawb)
    unit_weight_v = _coalesce_value("unit_weight", edited_values, extracted_mawb)
    unit_volume_v = _coalesce_value("unit_volume", edited_values, extracted_mawb)
    unit_length_v = _coalesce_value("unit_length", edited_values, extracted_mawb)
    nature_of_goods_v = _coalesce_value("nature_of_goods", edited_values, extracted_mawb)
    commodity_v = _coalesce_value("commodity", edited_values, extracted_mawb)

    if "origin" in selected_fields and origin_v:
        payload["origin"] = str(origin_v).strip().upper()
    if "destination" in selected_fields and destination_v:
        payload["destination"] = str(destination_v).strip().upper()
    if "pieces" in selected_fields:
        p_int = _to_int(pieces_v)
        if p_int is not None:
            payload["stated_pieces"] = p_int
    if "weight" in selected_fields:
        w_float = _to_float(weight_v)
        if w_float is not None:
            payload["stated_weight"] = w_float
    if "chargeable_weight" in selected_fields:
        cw_float = _to_float(chargeable_weight_v)
        if cw_float is not None:
            payload["chargeable_weight"] = cw_float
    if "volume" in selected_fields:
        vol_float = _to_float(volume_v)
        if vol_float is not None:
            payload["volume"] = vol_float
    if "goods_description" in selected_fields and goods_v:
        payload["shipment_description"] = str(goods_v)
    if "currency" in selected_fields and currency_v:
        payload["currency"] = str(currency_v).strip().upper()
    if "rate" in selected_fields:
        rate_float = _to_float(rate_v)
        if rate_float is not None:
            payload["rate"] = rate_float
    if "total_charge" in selected_fields:
        total_charge_float = _to_float(total_charge_v)
        if total_charge_float is not None:
            payload["total_charge"] = total_charge_float
    if "declared_value_carriage" in selected_fields and declared_value_carriage_v not in (None, "", "—"):
        payload["declared_value_carriage"] = str(declared_value_carriage_v)
    if "declared_value_customs" in selected_fields and declared_value_customs_v not in (None, "", "—"):
        payload["declared_value_customs"] = str(declared_value_customs_v)

    if "shipper" in selected_fields and shipper_v:
        shipper = _ensure("shipper")
        shipper["name"] = str(shipper_v)
    if "consignee" in selected_fields and consignee_v:
        consignee = _ensure("consignee")
        consignee["name"] = str(consignee_v)
    if "agent" in selected_fields and agent_v:
        agent = _ensure("agent")
        agent["agent_name"] = str(agent_v)
    if "notify_party" in selected_fields and notify_party_v:
        notify_party = _ensure("notify_party")
        notify_party["name"] = str(notify_party_v)

    if "flight_date" in selected_fields and flight_date_v:
        payload["date_of_journey"] = str(flight_date_v)

    if "flight_number" in selected_fields and flight_num_v:
        raw_flight = str(flight_num_v or "").strip().upper()
        carrier = "".join(ch for ch in raw_flight[:2] if ch.isalpha())
        flight_number = "".join(ch for ch in raw_flight[2:] if ch.isdigit())
        if carrier and flight_number:
            payload["requested_flight"] = [{
                "carrier_code": carrier,
                "flight_number": flight_number,
                "flight_date": str(flight_date_v or payload.get("date_of_journey") or ""),
                "origin": payload.get("origin"),
                "destination": payload.get("destination"),
            }]

    if "hs_code" in selected_fields and hs_code_v:
        payload["harmonised_commodity_code"] = str(hs_code_v)

    if "special_handling" in selected_fields and special_handling_v:
        shc = str(special_handling_v).replace(";", ",")
        payload["handling_codes"] = [c.strip() for c in shc.split(",") if c.strip()]

    if "unit_weight" in selected_fields and unit_weight_v:
        uom = _ensure("unit_of_measures")
        uom["weight"] = str(unit_weight_v).strip().lower()
    if "unit_volume" in selected_fields and unit_volume_v:
        uom = _ensure("unit_of_measures")
        uom["volume"] = str(unit_volume_v).strip().lower()
    if "unit_length" in selected_fields and unit_length_v:
        uom = _ensure("unit_of_measures")
        uom["length"] = str(unit_length_v).strip().lower()

    # Ensure minimal required structures remain present.
    # NOTE: do NOT fabricate a "routing" default here — a placeholder entry with
    # a fake carrier ("XX") triggered ICO_AWB_010 "Invalid ULD". Routing isn't a
    # user-editable field (not in MAWB_POST_EDITABLE_FIELDS), so leave whatever
    # routing already exists on the fetched AWB record untouched.
    payload.setdefault("unit_of_measures", {"weight": "kg", "volume": "cbm", "length": "m"})
    payload.setdefault("applicable_charges", {"rating_details": [{
        "nature_of_goods": payload.get("shipment_description") or "GENERAL CARGO",
        "pieces": payload.get("stated_pieces") or 1,
        "weight": payload.get("stated_weight") or 0.0,
        "commodity": "GEN",
    }]})

    rating_details = payload.get("applicable_charges", {}).get("rating_details", [])
    if not isinstance(rating_details, list) or not rating_details:
        payload.setdefault("applicable_charges", {})
        payload["applicable_charges"]["rating_details"] = [{
            "nature_of_goods": payload.get("shipment_description") or "GENERAL CARGO",
            "pieces": payload.get("stated_pieces") or 1,
            "weight": payload.get("stated_weight") or 0.0,
            "commodity": "GEN",
        }]
        rating_details = payload["applicable_charges"]["rating_details"]

    # iCargo validation rule: stated pieces/weight must match rating pieces/weight.
    # Keep rating_details[0] aligned with current payload values to avoid ICO_AWB_009.
    if payload.get("stated_pieces") is not None:
        rating_details[0]["pieces"] = payload.get("stated_pieces")
    if payload.get("stated_weight") is not None:
        rating_details[0]["weight"] = payload.get("stated_weight")

    if "nature_of_goods" in selected_fields and nature_of_goods_v:
        rating_details[0]["nature_of_goods"] = str(nature_of_goods_v)
    if "commodity" in selected_fields and commodity_v:
        rating_details[0]["commodity"] = str(commodity_v)

    return _empty_placeholder_uld_sections(payload)


def _bisect_hawb_payload_fields(ic: "ICargoIBSClient", awb_code: str, raw_hawb: dict) -> list[tuple[str, bool, str]]:
    """Debug helper: POST the raw HAWB record repeatedly, each time dropping one
    top-level key, to find which field the write endpoint rejects (stops at the
    first key whose removal makes the call succeed).
    """
    results: list[tuple[str, bool, str]] = []
    for key in list(raw_hawb.keys()):
        trial = {k: v for k, v in raw_hawb.items() if k != key}
        try:
            ic.save_hawbs(awb_code, [trial])
            results.append((key, True, "OK without this field"))
            break
        except Exception as e:
            results.append((key, False, str(e)))
    return results


# Fields observed in the raw GET record that look like read-only/legacy business
# extras rather than core update data — the first suspects for an unknown-field
# rejection when no single-field removal fixes the write.
_HAWB_EXOTIC_FIELDS = [
    "handling_codes", "dimension", "other_customs_information",
    "unit_of_measures", "remarks", "slac_pieces",
]


def _test_minimal_hawb_payload(ic: "ICargoIBSClient", awb_code: str, raw_hawb: dict) -> tuple[bool, str, dict]:
    """Try a payload stripped of all exotic fields at once; if it succeeds, add
    each exotic field back one at a time to find which one(s) break it.
    """
    minimal = {k: v for k, v in raw_hawb.items() if k not in _HAWB_EXOTIC_FIELDS}
    try:
        msg = ic.save_hawbs(awb_code, [dict(minimal)])
        return True, f"Minimal payload OK: {msg}", minimal
    except Exception as e:
        return False, str(e), minimal


def _readd_exotic_fields_one_by_one(ic: "ICargoIBSClient", awb_code: str, raw_hawb: dict, minimal: dict) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for key in _HAWB_EXOTIC_FIELDS:
        if key not in raw_hawb:
            continue
        trial = dict(minimal)
        trial[key] = raw_hawb[key]
        try:
            ic.save_hawbs(awb_code, [trial])
            results.append((key, True, "OK with this field too"))
        except Exception as e:
            results.append((key, False, str(e)))
    return results


def _build_hawb_detail_payload(
    awb_code: str,
    hawb_data: dict,
    selected_fields: set[str],
    edited_values: dict[str, object],
    raw_icargo_hawb: Optional[dict] = None,
) -> dict:
    """Build a HAWB update payload matching the real iCargo Swagger schema for
    POST /awbs/{awb}/hawbs (array body): awb/hawb identifiers (with dash),
    3-letter IATA origin/destination, bare pieces/weight, harmonised_commodity_code,
    nested shipper/consignee objects, and a unit_of_measures block.

    `raw_icargo_hawb`, when available, is the record as returned live by iCargo's
    own GET — it's the base for any field NOT explicitly selected for edit, so we
    never resend our own PDF-extraction values/formats (e.g. internal composite
    location codes like "ITMOD" instead of the real IATA code "BLQ") for fields
    the user didn't touch.
    """
    out: dict = dict(raw_icargo_hawb) if raw_icargo_hawb else {}
    hawb_num_v = _coalesce_value("hawb_number", edited_values, hawb_data)
    hawb_num = str(hawb_num_v or hawb_data.get("hawb") or out.get("hawb") or "").strip()
    out["awb"] = awb_code
    out["hawb"] = hawb_num

    origin_v = _coalesce_value("origin", edited_values, hawb_data)
    destination_v = _coalesce_value("destination", edited_values, hawb_data)
    pieces_v = _coalesce_value("pieces", edited_values, hawb_data)
    weight_v = _coalesce_value("weight", edited_values, hawb_data)
    goods_v = _coalesce_value("goods_description", edited_values, hawb_data)
    shipper_v = _coalesce_value("shipper", edited_values, hawb_data)
    consignee_v = _coalesce_value("consignee", edited_values, hawb_data)
    hs_code_v = _coalesce_value("hs_code", edited_values, hawb_data)
    special_handling_v = _coalesce_value("special_handling", edited_values, hawb_data)

    # Required by API schema — only overwrite with our own extracted value when
    # the user actually selected that field; otherwise keep iCargo's own value.
    if "origin" in selected_fields and origin_v:
        out["origin"] = str(origin_v).strip().upper()
    else:
        out.setdefault("origin", str(origin_v or "").strip().upper())
    if "destination" in selected_fields and destination_v:
        out["destination"] = str(destination_v).strip().upper()
    else:
        out.setdefault("destination", str(destination_v or "").strip().upper())
    if "pieces" in selected_fields:
        p_int = _to_int(pieces_v)
        if p_int is not None:
            out["pieces"] = p_int
    else:
        out.setdefault("pieces", _to_int(pieces_v) or 0)
    if "weight" in selected_fields:
        w_float = _to_float(weight_v)
        if w_float is not None:
            out["weight"] = w_float
    else:
        out.setdefault("weight", _to_float(weight_v) or 0.0)
    if "goods_description" in selected_fields and goods_v:
        out["shipment_description"] = str(goods_v)
    else:
        out.setdefault("shipment_description", str(goods_v or "GENERAL CARGO"))
    out.setdefault("unit_of_measures", {"weight": "kg", "volume": "cbm", "length": "m"})

    chargeable_weight_v = _coalesce_value("chargeable_weight", edited_values, hawb_data)
    volume_v = _coalesce_value("volume", edited_values, hawb_data)
    total_charge_v = _coalesce_value("total_charge", edited_values, hawb_data)
    declared_value_carriage_v = _coalesce_value("declared_value_carriage", edited_values, hawb_data)
    declared_value_customs_v = _coalesce_value("declared_value_customs", edited_values, hawb_data)
    rate_v = _coalesce_value("rate", edited_values, hawb_data)
    notify_party_v = _coalesce_value("notify_party", edited_values, hawb_data)
    flight_date_v = _coalesce_value("flight_date", edited_values, hawb_data)
    flight_num_v = _coalesce_value("flight_number", edited_values, hawb_data)
    dimensions_v = _coalesce_value("dimensions", edited_values, hawb_data)

    # Optional mapped fields when selected
    if "hs_code" in selected_fields and hs_code_v:
        out["harmonised_commodity_code"] = str(hs_code_v)
    if "special_handling" in selected_fields and special_handling_v:
        shc = str(special_handling_v or "").replace(";", ",")
        out["handling_codes"] = [c.strip() for c in shc.split(",") if c.strip()]
    if "shipper" in selected_fields and shipper_v:
        out["shipper"] = {
            "name": str(shipper_v),
            "address": hawb_data.get("shipper_street") or "",
            "city": hawb_data.get("shipper_city") or "",
            "state": hawb_data.get("shipper_province") or "",
            "post_code": hawb_data.get("shipper_zip") or "",
            "country": hawb_data.get("shipper_country") or "",
        }
    if "consignee" in selected_fields and consignee_v:
        out["consignee"] = {
            "name": str(consignee_v),
            "address": hawb_data.get("consignee_street") or "",
            "city": hawb_data.get("consignee_city") or "",
            "state": hawb_data.get("consignee_province") or "",
            "post_code": hawb_data.get("consignee_zip") or "",
            "country": hawb_data.get("consignee_country") or "",
        }

    if "notify_party" in selected_fields and notify_party_v:
        out["remarks"] = str(notify_party_v)

    if "chargeable_weight" in selected_fields:
        cw_float = _to_float(chargeable_weight_v)
        if cw_float is not None:
            out["chargeable_weight"] = cw_float
    if "volume" in selected_fields:
        vol_float = _to_float(volume_v)
        if vol_float is not None:
            out["volume"] = vol_float
    if "rate" in selected_fields:
        rate_float = _to_float(rate_v)
        if rate_float is not None:
            out["rate"] = rate_float
    if "total_charge" in selected_fields:
        total_charge_float = _to_float(total_charge_v)
        if total_charge_float is not None:
            out["total_charge"] = total_charge_float
    if "declared_value_carriage" in selected_fields and declared_value_carriage_v not in (None, "", "—"):
        out["declared_value_carriage"] = str(declared_value_carriage_v)
    if "declared_value_customs" in selected_fields and declared_value_customs_v not in (None, "", "—"):
        out["declared_value_customs"] = str(declared_value_customs_v)

    if "flight_number" in selected_fields and flight_num_v:
        raw_flight = str(flight_num_v).strip().upper()
        carrier = "".join(ch for ch in raw_flight[:2] if ch.isalpha())
        flight_number = "".join(ch for ch in raw_flight[2:] if ch.isdigit())
        if carrier and flight_number:
            out["requested_flight"] = [{
                "carrier_code": carrier,
                "flight_number": flight_number,
                "flight_date": str(flight_date_v or ""),
                "origin": out.get("origin"),
                "destination": out.get("destination"),
            }]

    if "dimensions" in selected_fields and dimensions_v:
        out["dimension"] = str(dimensions_v)

    return out


def _awb_form(awb_num: str, data: dict):
    """Render AWB fields in a grid mirroring the real AWB layout."""
    # Shipper | Consignee
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**Shipper**")
            st.markdown(f"**{_val(data.get('shipper'))}**")
            st.caption(_fmt_addr(data, "shipper"))
    with c2:
        with st.container(border=True):
            st.markdown("**Consignee**")
            st.markdown(f"**{_val(data.get('consignee'))}**")
            st.caption(_fmt_addr(data, "consignee"))

    # Agent | Routing
    c3, c4 = st.columns(2)
    with c3:
        with st.container(border=True):
            st.markdown("**Issuing Carrier's Agent**")
            st.markdown(f"**{_val(data.get('agent'))}**")
            st.caption(_fmt_addr(data, "agent"))
    with c4:
        with st.container(border=True):
            st.markdown("**AWB / Routing**")
            st.write(f"🔖 AWB: `{awb_num}`")
            st.write(f"✈️ {_val(data.get('origin'))} → {_val(data.get('destination'))}")
            st.write(f"🛫 Flight: **{_val(data.get('flight_number'))}**")
            st.write(f"📅 Date: **{_val(data.get('flight_date'))}**")

    # Notify party (if present)
    notify = data.get("notify_party")
    if notify and notify not in ("null", ""):
        with st.container(border=True):
            st.markdown("**Notify Party**")
            st.text(notify)

    # Cargo figures
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        with st.container(border=True):
            st.markdown("**Pcs (RCP)**")
            st.markdown(f"### {_val(data.get('pieces'))}")
    with c6:
        with st.container(border=True):
            st.markdown("**Gross Weight**")
            st.markdown(f"### {_val(data.get('weight'), ' kg')}")
    with c7:
        with st.container(border=True):
            st.markdown("**Chargeable Wt**")
            st.markdown(f"### {_val(data.get('chargeable_weight'), ' kg')}")
    with c8:
        with st.container(border=True):
            st.markdown("**Rate / Total**")
            st.write(f"Rate: **{_val(data.get('rate'))}**")
            st.write(f"Total: **{_val(data.get('total_charge'))}**")
            st.write(f"Currency: **{_val(data.get('currency'))}**")

    # Volume / Dimensions / HS / Special handling
    extras = [
        ("Volume", _val(data.get("volume"), " m³")),
        ("Dimensions", _val(data.get("dimensions"))),
        ("HS Code", _val(data.get("hs_code"))),
        ("Special Handling", _val(data.get("special_handling"))),
        ("Decl. Value Carriage", _val(data.get("declared_value_carriage"))),
        ("Decl. Value Customs", _val(data.get("declared_value_customs"))),
    ]
    filled = [(lbl, v) for lbl, v in extras if v != "—"]
    if filled:
        ecols = st.columns(len(filled))
        for col, (lbl, v) in zip(ecols, filled):
            col.metric(lbl, v)

    # Goods description
    with st.container(border=True):
        st.markdown("**Nature and Quantity of Goods**")
        st.text(data.get("goods_description") or "—")


def _hawb_form(hawb_num: str, data: dict):
    """Render House AWB fields."""
    # Shipper | Consignee
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**Shipper**")
            st.markdown(f"**{_val(data.get('shipper'))}**")
            st.caption(_fmt_addr(data, "shipper"))
    with c2:
        with st.container(border=True):
            st.markdown("**Consignee**")
            st.markdown(f"**{_val(data.get('consignee'))}**")
            st.caption(_fmt_addr(data, "consignee"))

    # Notify party (HAWB-specific)
    notify = data.get("notify_party")
    if notify and notify not in ("null", ""):
        with st.container(border=True):
            st.markdown("**Notify Party**")
            st.text(notify)

    # Routing
    with st.container(border=True):
        st.markdown("**Routing**")
        ca, cb, cc, cd = st.columns(4)
        ca.metric("Origin", _val(data.get("origin")))
        cb.metric("Destination", _val(data.get("destination")))
        cc.metric("Flight", _val(data.get("flight_number")))
        cd.metric("Date", _val(data.get("flight_date")))

    # Cargo figures
    c3, c4, c5, c6, c7 = st.columns(5)
    with c3:
        with st.container(border=True):
            st.markdown("**Pcs**")
            st.markdown(f"### {_val(data.get('pieces'))}")
    with c4:
        with st.container(border=True):
            st.markdown("**Gross Wt**")
            st.markdown(f"### {_val(data.get('weight'), ' kg')}")
    with c5:
        with st.container(border=True):
            st.markdown("**Chg Wt**")
            st.markdown(f"### {_val(data.get('chargeable_weight'), ' kg')}")
    with c6:
        with st.container(border=True):
            st.markdown("**Volume**")
            st.markdown(f"### {_val(data.get('volume'), ' m³')}")
    with c7:
        with st.container(border=True):
            st.markdown("**Total Charge**")
            st.markdown(f"### {_val(data.get('total_charge'))}")

    # Commodity details
    cd1, cd2 = st.columns(2)
    with cd1:
        with st.container(border=True):
            st.markdown("**HS Code**")
            st.code(data.get("hs_code") or "—")
    with cd2:
        with st.container(border=True):
            st.markdown("**Special Handling**")
            sh = data.get("special_handling")
            st.code(sh if sh and sh != "null" else "—")

    # Goods description
    with st.container(border=True):
        st.markdown("**Description of Goods**")
        st.text(data.get("goods_description") or "—")

    # Declared values
    dv1, dv2, dv3 = st.columns(3)
    dv1.metric("Dimensions", _val(data.get("dimensions")))
    dv2.metric("Decl. Value Carriage", _val(data.get("declared_value_carriage")))
    dv3.metric("Decl. Value Customs", _val(data.get("declared_value_customs")))


# ── Presplit helper ───────────────────────────────────────────────────────
def _split_pdf(raw_pdf: bytes, fast: bool = False) -> list[dict]:
    """
    Split the PDF into one document per MAWB.
    fast=True  → parallel 300 DPI Tesseract on top 20% of each page (recommended)
    fast=False → full-quality sequential OCR on the whole page (difficult scans)
    """
    extractor = PDFTextExtractor()
    presplitter = AwbDocumentPreSplitter(extractor=extractor)
    if fast:
        return presplitter.presplit_pdf_fast(raw_pdf)
    return presplitter.presplit_pdf_with_text(raw_pdf, use_extractor=True)


def _extract_pdfs_from_upload(uploaded) -> list[dict]:
    """
    Normalises a file upload to a list of {"name": str, "bytes": bytes} dicts.
    Accepts a single PDF or a ZIP archive containing one or more PDFs.
    Files inside the ZIP are sorted by name for deterministic ordering.
    Non-PDF entries and macOS metadata folders inside the ZIP are silently skipped.
    """
    raw = uploaded.read()
    if uploaded.name.lower().endswith(".zip"):
        results = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            pdf_entries = sorted(
                name for name in zf.namelist()
                if name.lower().endswith(".pdf") and not name.startswith("__MACOSX")
            )
            for entry in pdf_entries:
                results.append({"name": entry.split("/")[-1], "bytes": zf.read(entry)})
        return results
    return [{"name": uploaded.name, "bytes": raw}]


def _list_polling_pdf_files(input_dir: str | Path, processed_dir: str | Path) -> list[Path]:
    input_path = Path(input_dir).expanduser()
    processed_path = Path(processed_dir).expanduser()
    input_path.mkdir(parents=True, exist_ok=True)
    processed_path.mkdir(parents=True, exist_ok=True)
    return sorted(path for path in input_path.glob("*.pdf") if path.is_file())


def _load_next_polling_pdf(input_dir: str | Path, processed_dir: str | Path) -> dict | None:
    pdf_paths = _list_polling_pdf_files(input_dir=input_dir, processed_dir=processed_dir)
    if not pdf_paths:
        return None
    next_path = pdf_paths[0]
    return {
        "name": next_path.name,
        "bytes": next_path.read_bytes(),
        "path": next_path,
    }


def _move_polling_file_to_processed(file_path: str | Path, processed_dir: str | Path) -> Path:
    source = Path(file_path).expanduser()
    dest_dir = Path(processed_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    destination = dest_dir / source.name
    if destination.exists():
        unique_suffix = int(time.time() * 1000)
        destination = dest_dir / f"{source.stem}_{unique_suffix}{source.suffix}"

    source.replace(destination)
    return destination


# ── Main page ──────────────────────────────────────────────────────────────
def render_pdf_upload(on_back):
    st.markdown(
        """
        <section class="msc-page-header">
            <div class="msc-kicker">PDF workflow</div>
            <h1>AWB extraction</h1>
            <p>Upload a PDF and choose between Claude Vision (cloud API) or MSC Tech AI (file-based) for AWB extraction.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to Home", type="secondary"):
        on_back()
        st.stop()

    # ── Session state defaults ─────────────────────────────────────────────
    for key, val in {
        "raw_pdf_bytes": None,
        "pdf_name": None,
        "batch_pdfs": [],
        "split_documents": None,
        "split_mode": "fast",
        "awb_results": None,
        "vision_refined_awbs": {},
        "icargo_compare_cache": {},
        "debug_page_texts": None,
        "debug_pdf_name": None,
        "folder_polling": False,
        "polling_input_dir": r"C:\TEMP\POC",
        "polling_processed_dir": r"C:\TEMP\POC\PROCESSED",
        "polling_current_path": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = val

    polling_mode = bool(st.session_state.get("folder_polling", False))
    polling_input_dir = Path(st.session_state.get("polling_input_dir", r"C:\TEMP\POC")).expanduser()
    polling_processed_dir = Path(st.session_state.get("polling_processed_dir", r"C:\TEMP\POC\PROCESSED")).expanduser()
    current_source_name = ""

    if polling_mode:
        st.info(
            "📡 Polling folder mode enabled. The app is watching "
            f"**{polling_input_dir}** and will process one PDF at a time."
        )
        st.caption(
            "Processed files will be moved to "
            f"**{polling_processed_dir}** once you confirm the simulated iCargo update."
        )

    # ── Provider selection ───────────────────────────────────────────────
    provider_name = st.selectbox(
        "Vision provider",
        options=["claude", "msc_tech_ai"],
        format_func=lambda v: {
            "claude": "Claude Vision (API)",
            "msc_tech_ai": "MSC Tech AI (File-based)"
        }.get(v, v),
        index=0,
        key="vision_provider_select",
    )

    if provider_name == "msc_tech_ai":
        st.info(
            "MSC Tech AI mode: send PNGs and receive JSON results via either a local OneDrive-synced folder or a browser-accessible SharePoint/OneDrive URL. "
            "The app resolves browser URLs to the local OneDrive sync folder of the current user, and the selected folders are persisted in .env."
        )
        st.markdown(
            "**Note:** the user running the app must have the SharePoint library synced with OneDrive. "
            "Enter a local path or a SharePoint/OneDrive URL; the app will try to resolve the URL to a valid local path."
        )

        if "msc_png_folder" not in st.session_state:
            st.session_state["msc_png_folder"] = os.getenv("MSC_TECH_PNG_FOLDER", "")
        if "msc_json_folder" not in st.session_state:
            st.session_state["msc_json_folder"] = os.getenv("MSC_TECH_JSON_FOLDER", "")
        if "msc_group_label" not in st.session_state:
            st.session_state["msc_group_label"] = os.getenv("MSC_TECH_GROUP_LABEL", "default")

        png_folder = st.text_input(
            "PNG inbox folder or SharePoint folder URL",
            key="msc_png_folder",
            placeholder="C:/Users/.../OneDrive - YourSharePointFolder/png-in or https://...",
        )

        json_folder = st.text_input(
            "JSON output folder or SharePoint folder URL",
            key="msc_json_folder",
            placeholder="C:/Users/.../OneDrive - YourSharePointFolder/json-out or https://...",
        )

        group_label = st.text_input(
            "MAWB + HAWB group label",
            key="msc_group_label",
            placeholder="e.g. MAWB-001",
        )

        if png_folder:
            _persist_msc_tech_env("MSC_TECH_PNG_FOLDER", png_folder)
        if json_folder:
            _persist_msc_tech_env("MSC_TECH_JSON_FOLDER", json_folder)
        if group_label:
            _persist_msc_tech_env("MSC_TECH_GROUP_LABEL", group_label)

    # ── Upload / polling selection ───────────────────────────────────────
    uploaded = None
    if polling_mode:
        polling_pdf = _load_next_polling_pdf(input_dir=polling_input_dir, processed_dir=polling_processed_dir)
        if polling_pdf is None:
            st.warning("⏳ No PDF found yet in the polling folder. Waiting for the next file...")
            col_wait, col_stop = st.columns([2, 1])
            with col_wait:
                if st.button("🔁 Refresh polling folder", type="secondary"):
                    st.rerun()
            with col_stop:
                if st.button("🛑 Stop polling mode", type="secondary"):
                    st.session_state["folder_polling"] = False
                    st.session_state["polling_current_path"] = None
                    st.rerun()
            return

        current_poll_path = str(polling_pdf["path"])
        if st.session_state.get("polling_current_path") != current_poll_path:
            st.session_state["pdf_name"] = polling_pdf["name"]
            st.session_state["batch_pdfs"] = [{"name": polling_pdf["name"], "bytes": polling_pdf["bytes"]}]
            st.session_state["raw_pdf_bytes"] = polling_pdf["bytes"]
            st.session_state["split_documents"] = None
            st.session_state["awb_results"] = None
            st.session_state["vision_refined_awbs"] = {}
            st.session_state["debug_page_texts"] = None
            st.session_state["debug_pdf_name"] = None
            st.session_state["polling_current_path"] = current_poll_path
            st.rerun()

        batch_pdfs = st.session_state["batch_pdfs"]
        raw_pdf = batch_pdfs[0]["bytes"]
        is_zip = False
        current_source_name = polling_pdf["name"]
        st.success(f"📄 {polling_pdf['name']} — {len(raw_pdf):,} bytes (polling folder)")
        st.info(f"📡 Current file from polling queue: {current_poll_path}")
    else:
        uploaded = st.file_uploader(
            "Select a PDF or a ZIP archive containing PDFs",
            type=["pdf", "zip"],
        )
        if not uploaded:
            st.info("Upload a PDF or a ZIP archive containing PDFs to get started.")
            return

        # Normalise upload → list of PDFs; only re-parse when the file changes.
        if st.session_state.get("pdf_name") != uploaded.name:
            batch_pdfs = _extract_pdfs_from_upload(uploaded)
            if not batch_pdfs:
                st.error("No PDF files found in the archive.")
                return
            st.session_state["pdf_name"] = uploaded.name
            st.session_state["batch_pdfs"] = batch_pdfs
            st.session_state["raw_pdf_bytes"] = batch_pdfs[0]["bytes"]
            st.session_state["split_documents"] = None
            st.session_state["awb_results"] = None
            st.session_state["vision_refined_awbs"] = {}
            st.session_state["debug_page_texts"] = None
            st.session_state["debug_pdf_name"] = None

        batch_pdfs = st.session_state["batch_pdfs"]
        if not batch_pdfs:
            st.error("No PDF files to process. Please re-upload the file.")
            return

        raw_pdf = batch_pdfs[0]["bytes"]
        is_zip = uploaded.name.lower().endswith(".zip")
        current_source_name = uploaded.name

        if is_zip:
            st.success(f"📦 {uploaded.name} — {len(batch_pdfs)} PDF file(s) found")
            with st.expander("📄 Files in archive", expanded=False):
                for p in batch_pdfs:
                    st.caption(f"• {p['name']} ({len(p['bytes']):,} bytes)")
        else:
            st.success(f"📄 {uploaded.name} — {uploaded.size:,} bytes")

    if not polling_mode:
        batch_pdfs = st.session_state["batch_pdfs"]
        if not batch_pdfs:
            st.error("No PDF files to process. Please re-upload the file.")
            return

    # raw_pdf kept for single-file features (debug panel, PNG preview)
    raw_pdf = st.session_state.get("raw_pdf_bytes") or raw_pdf

    # ── Split mode selector ────────────────────────────────────────────────
    split_mode = st.radio(
        "Pre-split mode",
        options=["fast", "normal"],
        format_func=lambda x: (
            "⚡ Smart — 300 DPI, top 20% of page, parallel (recommended)"
            if x == "fast"
            else "🔬 Normal — 200 DPI, full page, sequential (for difficult scans)"
        ),
        horizontal=True,
        key="split_mode_radio",
    )
    # If mode changed, force a re-split (keep batch_pdfs — they come from the file)
    if split_mode != st.session_state.get("split_mode"):
        st.session_state["split_mode"] = split_mode
        st.session_state["split_documents"] = None
        st.session_state["awb_results"] = None
        st.session_state["vision_refined_awbs"] = {}
        st.session_state["debug_page_texts"] = None
        st.session_state["debug_pdf_name"] = None
        st.rerun()

    # ── Split ──────────────────────────────────────────────────────────────
    use_fast = (st.session_state["split_mode"] == "fast")
    if st.session_state["split_documents"] is None:
        mode_label = "⚡ smart" if use_fast else "🔬 normal"
        src_label = f"{len(batch_pdfs)} PDF(s)" if is_zip else "the PDF"
        with st.spinner(f"Detecting AWB documents in {src_label} ({mode_label})..."):
            try:
                all_docs: list[dict] = []
                for pdf_entry in batch_pdfs:
                    docs = _split_pdf(pdf_entry["bytes"], fast=use_fast)
                    for doc in docs:
                        # Tag each split document with its source PDF so the
                        # extraction step can use the correct PDF bytes.
                        doc["_pdf_name"] = pdf_entry["name"]
                        doc["_pdf_bytes"] = pdf_entry["bytes"]
                    all_docs.extend(docs)
                st.session_state["split_documents"] = all_docs
            except Exception as e:
                st.error(f"Split error: {e}")
                return

    split_docs: list[dict] = st.session_state["split_documents"]

    if not split_docs:
        st.error("No MAWB document found in the PDF. Please ensure the PDF contains an Air Waybill.")
        return

    st.info(f"**{len(split_docs)} document(s) detected:** {', '.join(d.get('awb_number') or '—' for d in split_docs)}")

    # ── Debug: raw text + split boundaries ────────────────────────────────
    with st.expander("🔍 Debug split — raw text per page", expanded=False):
        if is_zip:
            st.info(
                f"Showing raw page text for the first PDF in the archive "
                f"(**{batch_pdfs[0]['name']}**) only."
            )
        mode_badge = "⚡ Smart (300 DPI, top 20%)" if use_fast else "🔬 Normal (200 DPI, full page)"
        st.caption(
            f"Split mode used: **{mode_badge}**. "
            "Text extracted by pdfplumber/Tesseract (before Vision). "
            "Lines marked **\u2501\u2501 DOCUMENT START \u2026** indicate boundaries detected by the pre-splitter."
        )

        # Build a set of (page → doc_label) for quick lookup
        page_to_doc: dict[int, str] = {}
        for doc in split_docs:
            for p in range(doc.get("start_page", 1), doc.get("end_page", doc.get("start_page", 1)) + 1):
                page_to_doc[p] = doc.get("awb_number") or "—"

        # Re-extract raw page texts (cached in session state to avoid re-running)
        if "debug_page_texts" not in st.session_state or st.session_state.get("debug_pdf_name") != current_source_name:
            import io as _io
            try:
                import pdfplumber as _pdfplumber
                raw_page_texts: dict[int, str] = {}
                with _pdfplumber.open(_io.BytesIO(raw_pdf)) as _pdf:
                    for i, _page in enumerate(_pdf.pages):
                        raw_page_texts[i + 1] = _page.extract_text() or "(no native text — scanned page)"
                st.session_state["debug_page_texts"] = raw_page_texts
                st.session_state["debug_pdf_name"] = current_source_name
            except Exception as _e:
                st.warning(f"Could not extract raw text: {_e}")
                raw_page_texts = {}
        else:
            raw_page_texts = st.session_state["debug_page_texts"]

        if raw_page_texts:
            prev_doc = None
            for page_num in sorted(raw_page_texts.keys()):
                doc_label = page_to_doc.get(page_num, "—")
                if doc_label != prev_doc:
                    st.markdown(
                        f"<div style='background:#1e3a5f;color:#7dd3fc;padding:6px 10px;"
                        f"border-radius:4px;font-family:monospace;font-size:0.85rem;margin:8px 0 2px;'>"
                        f"━━ DOCUMENT START &nbsp;<strong>AWB {doc_label}</strong>"
                        f"&nbsp;━━</div>",
                        unsafe_allow_html=True,
                    )
                    prev_doc = doc_label

                with st.container():
                    st.markdown(
                        f"<span style='font-size:0.78rem;color:#94a3b8;'>Page {page_num}</span>",
                        unsafe_allow_html=True,
                    )
                    st.code(raw_page_texts[page_num], language=None)

    st.divider()

    # ── Preview rendered PNGs (rotation-corrected, no Claude call) ─────────
    with st.expander("🖼 Preview rendered pages (rotation check — no Claude call)", expanded=False):
        st.caption(
            "Downloads a ZIP of the PNG images that would be sent to the selected provider. "
            "Use this to verify orientation correction before processing."
        )
        if st.button("📦 Build PNG preview ZIP", key="build_png_zip"):
            import io as _zip_io
            import zipfile as _zipfile
            try:
                import fitz as _fitz
            except ImportError:
                st.error("PyMuPDF not installed. Run: pip install pymupdf")
                return

            buf = _zip_io.BytesIO()
            total_pages = 0
            with _zipfile.ZipFile(buf, "w", compression=_zipfile.ZIP_DEFLATED) as zf:
                # Track the currently open fitz document to avoid re-opening
                # the same PDF repeatedly when multiple split_docs share a source.
                _current_pdf_bytes = None
                _fitz_doc = None
                for doc_idx, doc in enumerate(split_docs):
                    doc_pdf_bytes = doc.get("_pdf_bytes") or raw_pdf
                    if doc_pdf_bytes is not _current_pdf_bytes:
                        if _fitz_doc:
                            _fitz_doc.close()
                        _fitz_doc = _fitz.open(stream=doc_pdf_bytes, filetype="pdf")
                        _current_pdf_bytes = doc_pdf_bytes
                    awb_label = doc.get("awb_number") or f"DOC_{doc_idx + 1}"
                    # In ZIP/batch mode prefix with the source PDF name for clarity
                    if is_zip and doc.get("_pdf_name"):
                        pdf_stem = doc["_pdf_name"].rsplit(".", 1)[0]
                        awb_label = f"{pdf_stem}/{awb_label}"
                    rotations: dict = doc.get("page_rotations") or {}
                    s = doc.get("start_page", 1)
                    e = doc.get("end_page", s)
                    _prev_correction = 0  # carry-forward for ambiguous pages within this doc
                    for page_num_1 in range(s, e + 1):
                        fitz_idx = page_num_1 - 1
                        if fitz_idx >= len(_fitz_doc):
                            continue
                        page = _fitz_doc[fitz_idx]
                        if page_num_1 in rotations:
                            correction = rotations[page_num_1]
                        else:
                            # Gradient orientation: compare score(0°) vs score(90°) directly.
                            # (Pair sums are always equal — mathematical identity.)
                            correction = _prev_correction  # carry-forward default
                            try:
                                import numpy as _np

                                def _gscore(px):
                                    a = _np.frombuffer(px.samples, dtype=_np.uint8).reshape(px.height, px.width, 3)
                                    d = (a.mean(axis=2) < 180).astype(_np.float32)
                                    cv = float(d.sum(axis=0).var())
                                    return float(d.sum(axis=1).var()) / (cv if cv > 0 else 1.0)

                                _lm = _fitz.Matrix(0.75, 0.75)
                                _s0 = _gscore(page.get_pixmap(matrix=_lm, colorspace=_fitz.csRGB))
                                _s90 = _gscore(page.get_pixmap(matrix=_lm.prerotate(90), colorspace=_fitz.csRGB))
                                if _s90 > _s0 * 1.15:
                                    correction = 90
                                elif _s0 > _s90 * 1.15:
                                    correction = 0
                            except Exception:
                                pass  # keep carry-forward
                        _prev_correction = correction
                        mat = _fitz.Matrix(1.5, 1.5).prerotate(correction) if correction else _fitz.Matrix(1.5, 1.5)
                        pix = page.get_pixmap(matrix=mat, colorspace=_fitz.csRGB)
                        png_bytes = pix.tobytes("png")
                        rot_label = f"_rot{correction}" if correction else ""
                        fname = f"{awb_label}/page_{page_num_1:03d}{rot_label}.png"
                        zf.writestr(fname, png_bytes)
                        total_pages += 1
                if _fitz_doc:
                    _fitz_doc.close()

            buf.seek(0)
            st.download_button(
                label=f"⬇️ Download {total_pages} PNG(s) as ZIP",
                data=buf.getvalue(),
                file_name=f"{current_source_name.rsplit('.', 1)[0]}_preview.zip",
                mime="application/zip",
                key="download_png_zip",
            )
            st.success(f"✅ {total_pages} page(s) rendered. Check the ZIP to verify orientation.")

    # ── Extract All ────────────────────────────────────────────────────────
    col_extract, col_reset = st.columns([2, 1])
    with col_extract:
        provider_labels = {
            "claude": "Claude Vision",
            "msc_tech_ai": "MSC Tech AI"
        }
        provider_label = provider_labels.get(provider_name, "Unknown")
        extract_btn = st.button(
            f"🚀 Extract all ({len(split_docs)}) with {provider_label}",
            type="primary",
            width='stretch',
        )
    with col_reset:
        if st.button("🗑 Reset", type="secondary", width='stretch'):
            st.session_state["awb_results"] = None
            st.session_state["vision_refined_awbs"] = {}
            st.rerun()

    invalid_msc_path = False
    msc_png_folder = st.session_state.get("msc_png_folder", "") if provider_name == "msc_tech_ai" else None
    msc_json_folder = st.session_state.get("msc_json_folder", "") if provider_name == "msc_tech_ai" else None
    if provider_name == "msc_tech_ai":
        for label, path in (
            ("PNG inbox folder", msc_png_folder),
            ("JSON output folder", msc_json_folder),
        ):
            if path:
                lower_path = path.lower()
                if lower_path.startswith("http://") or lower_path.startswith("https://") or lower_path.startswith("http:\\") or lower_path.startswith("https:\\"):
                    st.info(f"{label} looks like a browser URL. The app will resolve it to a local OneDrive sync path.")
                elif not Path(path).exists():
                    st.warning(f"{label} does not exist locally. Enter a valid local path or a browser URL.")
                    invalid_msc_path = True

    if extract_btn:
        if invalid_msc_path:
            st.warning("Fix the MSC Tech AI folder paths before extracting.")
        else:
            extractor = get_vision_extractor(
                provider_name=provider_name,
                png_folder=msc_png_folder,
                json_folder=msc_json_folder,
                group_label=st.session_state.get("msc_group_label") if provider_name == "msc_tech_ai" else None,
            )
        extracted: list[dict] = []  # each item: {"mawb": {...}, "hawbs": [...]}
        progress = st.progress(0, text="Starting...")
        errors: list[str] = []

        for i, doc in enumerate(split_docs):
            awb_num = doc.get("awb_number") or f"DOC_{i+1}"
            progress.progress(i / len(split_docs), text=f"Extracting {awb_num} ({i+1}/{len(split_docs)})...")
            try:
                result = extractor.extract_mawb_with_hawbs(
                    doc.get("_pdf_bytes") or raw_pdf,
                    start_page=doc.get("start_page", 1),
                    end_page=doc.get("end_page", doc.get("start_page", 1)),
                    page_rotations=doc.get("page_rotations"),
                    awb_number=doc.get("awb_number"),
                    group_label=st.session_state.get("msc_group_label", "") if provider_name == "msc_tech_ai" else None,
                )
                # Trust pre-validated AWB number from the splitter
                if doc.get("awb_number"):
                    result["mawb"]["awb_number"] = doc["awb_number"]
                # Carry the source PDF name through to the results for display
                result["_pdf_name"] = doc.get("_pdf_name", "")
                extracted.append(result)
            except Exception as e:
                errors.append(f"{awb_num}: {e}")
                st.warning(f"⚠️ Error for {awb_num}: {e}")

        progress.progress(1.0, text="Done!")
        st.session_state["awb_results"] = extracted
        if errors:
            st.warning(f"{len(errors)} error(s) during extraction.")
        else:
            total_hawbs = sum(len(r.get("hawbs", [])) for r in extracted)
            st.success(f"✅ {len(extracted)} MAWB(s) extracted, {total_hawbs} HAWB(s) total")

    # ── Results ────────────────────────────────────────────────────────────
    if not st.session_state.get("awb_results"):
        return

    results: list[dict] = st.session_state["awb_results"]

    if polling_mode and st.session_state.get("polling_current_path"):
        col_poll_action, col_next = st.columns([2, 1])
        with col_poll_action:
            if st.button("🧾 iCargo update (simulate writeback)", type="primary"):
                current_path = st.session_state.get("polling_current_path")
                if current_path:
                    moved = _move_polling_file_to_processed(current_path, polling_processed_dir)
                    st.success(
                        f"✅ File moved to processed folder: {moved.name}\n"
                        "The polling queue is now ready for the next PDF."
                    )
                    st.session_state["polling_current_path"] = None
                    st.session_state["split_documents"] = None
                    st.session_state["awb_results"] = None
                    st.session_state["vision_refined_awbs"] = {}
                    st.session_state["debug_page_texts"] = None
                    st.session_state["debug_pdf_name"] = None
                    st.rerun()
        with col_next:
            if st.button("➡️ Next polling file", type="secondary"):
                st.session_state["polling_current_path"] = None
                st.session_state["split_documents"] = None
                st.session_state["awb_results"] = None
                st.session_state["vision_refined_awbs"] = {}
                st.session_state["debug_page_texts"] = None
                st.session_state["debug_pdf_name"] = None
                st.rerun()
    st.divider()
    total_hawbs_all = sum(len(r.get("hawbs", [])) for r in results)
    st.subheader(f"Results: {len(results)} MAWB | {total_hawbs_all} HAWB")
    st.caption("Review extracted data, compare it with iCargo, then select the fields to update.")

    for idx, result in enumerate(results):
        raw_mawb = result.get("mawb") if isinstance(result.get("mawb"), dict) else {}
        raw_hawbs = result.get("hawbs") if isinstance(result.get("hawbs"), list) else []
        mawb_data = raw_mawb or {}
        hawbs: list[dict] = raw_hawbs
        awb_num = mawb_data.get("awb_number") or f"AWB_{idx+1}"
        refined = st.session_state["vision_refined_awbs"].get(awb_num)
        display_mawb = refined.get("mawb", refined) if refined else mawb_data
        display_hawbs = refined.get("hawbs", hawbs) if refined else hawbs
        if not isinstance(display_mawb, dict):
            display_mawb = {}
        if not isinstance(display_hawbs, list):
            display_hawbs = []

        hawb_badge = f" • {len(display_hawbs)} HAWB" if display_hawbs else ""
        pdf_badge = f"  [{result.get('_pdf_name')}]" if is_zip and result.get("_pdf_name") else ""
        with st.expander(f"MAWB {awb_num}{hawb_badge}{pdf_badge}", expanded=(idx == 0)):
            provider_labels = {
                "claude": "Claude Vision",
                "msc_tech_ai": "MSC Tech AI"
            }
            provider_label = provider_labels.get(provider_name, "Unknown")
            source_label = f"Source: {provider_label} (re-extracted)" if refined else f"Source: {provider_label}"
            st.caption(source_label)

            result_payload = refined if isinstance(refined, dict) else result
            assignment_mode = (result_payload or {}).get("hawb_assignment_mode")
            warnings = (result_payload or {}).get("warnings") or []
            if assignment_mode == "group_fallback":
                st.warning("MAWB number not found in the HAWB doc; using group assignment fallback.")
            for msg in warnings:
                if isinstance(msg, str) and msg.strip():
                    st.warning(msg)

            # ── MAWB fields ──────────────────────────────────────────────
            st.markdown("#### Master Air Waybill")
            _awb_form(awb_num, display_mawb)

            # ── HAWB subsections ─────────────────────────────────────────
            if display_hawbs:
                st.divider()
                st.markdown(f"#### House Air Waybills ({len(display_hawbs)})")
                for hi, hawb in enumerate(display_hawbs):
                    hawb_num = hawb.get("hawb_number") or f"HAWB_{hi+1}"
                    with st.expander(f"HAWB {hawb_num}", expanded=False):
                        _hawb_form(hawb_num, hawb)
            else:
                st.caption("No House AWB detected for this MAWB.")

            st.divider()

            action_col, download_col = st.columns([2, 1])
            with action_col:
                reextract_btn = st.button(
                    "Re-extract with Vision",
                    key=f"reextract_{idx}",
                    type="secondary",
                    width="stretch",
                    help="Run extraction again for this MAWB and its House AWBs.",
                )

            # Download JSON (full: mawb + hawbs)
            full_json = json.dumps({"mawb": display_mawb, "hawbs": display_hawbs}, indent=2, default=str)
            with download_col:
                st.download_button(
                    label="Download JSON",
                    data=full_json,
                    file_name=f"awb_{awb_num}.json",
                    mime="application/json",
                    key=f"dl_{idx}",
                    width="stretch",
                )

            if reextract_btn:
                try:
                    with st.spinner(f"Re-extracting {awb_num}..."):
                        ext = get_vision_extractor(
                            provider_name=provider_name,
                            png_folder=msc_png_folder,
                            json_folder=msc_json_folder,
                            group_label=st.session_state.get("msc_group_label") if provider_name == "msc_tech_ai" else None,
                        )
                        doc = next((d for d in split_docs if (d.get("awb_number") or "") == awb_num), None)
                        doc_pdf_bytes = doc.get("_pdf_bytes") if doc else None
                        if doc and doc_pdf_bytes:
                            new_result = ext.extract_mawb_with_hawbs(
                                doc_pdf_bytes,
                                start_page=doc.get("start_page", 1),
                                end_page=doc.get("end_page", doc.get("start_page", 1)),
                                page_rotations=doc.get("page_rotations"),
                                awb_number=doc.get("awb_number"),
                                group_label=st.session_state.get("msc_group_label", "") if provider_name == "msc_tech_ai" else None,
                            )
                        else:
                            text = (doc or {}).get("text", "") if doc else ""
                            if not text:
                                raise ValueError("Source text not available")
                            flat = ext.extract_from_text(text)
                            new_result = {"mawb": flat, "hawbs": []}
                        new_result["mawb"]["awb_number"] = awb_num
                        st.session_state["vision_refined_awbs"][awb_num] = new_result
                        st.rerun()
                except Exception as e:
                    st.error(f"Re-extraction failed: {e}")

            st.divider()

            # iCargo comparison (MAWB + HAWBs)
            st.markdown("#### iCargo Comparison")
            awb_for_icargo = _resolve_awb_for_icargo(str(awb_num), display_mawb)
            compare_state_key = f"{idx}:{awb_for_icargo}"
            fetch_compare = st.button(
                "Compare with iCargo",
                key=f"icargo_{idx}",
                type="primary",
                help="Fetch the current iCargo record and display field-level differences.",
            )

            if fetch_compare:
                st.session_state.pop(f"force_deselect_{compare_state_key}", None)
                if not awb_for_icargo:
                    st.warning(
                        "Invalid AWB number for iCargo query. "
                        f"Detected value: {awb_num}. Expected format: NNN-NNNNNNNN"
                    )
                else:
                    try:
                        ic = ICargoIBSClient()

                        with st.spinner(f"Fetching MAWB {awb_for_icargo} from iCargo..."):
                            icargo_result = ic.get_awb(awb_for_icargo)
                        icargo_flat = map_icargo_awb_ibs(icargo_result)
                        mawb_rows = diff_awb(display_mawb, icargo_flat)

                        hawb_compare_records: list[dict] = []
                        match_debug_rows: list[dict] = []
                        ic_hawb_list: list = []
                        hawbs_resp = None

                        with st.spinner(f"Fetching HAWBs for {awb_for_icargo} from iCargo..."):
                            try:
                                hawbs_resp = ic.get_hawbs(awb_for_icargo)
                            except Exception as he:
                                st.warning(f"⚠️ Could not fetch HAWBs from iCargo: {he}")

                        def _flatten_hawbs_resp(resp) -> list:
                            if isinstance(resp, list):
                                return resp
                            if not isinstance(resp, dict):
                                return []
                            for key in ("hawbs", "body", "data", "items", "result", "results"):
                                val = resp.get(key)
                                if isinstance(val, list) and val:
                                    return val
                                if isinstance(val, dict):
                                    inner = _flatten_hawbs_resp(val)
                                    if inner:
                                        return inner
                            return []

                        ic_hawb_list = _flatten_hawbs_resp(hawbs_resp)

                        def _ic_num(h: dict) -> str:
                            return str(
                                h.get("hawb")
                                or h.get("hawb_number")
                                or h.get("hawbNumber")
                                or h.get("houseAirwaybillNumber")
                                or h.get("hawbNo")
                                or ""
                            ).strip()

                        def _norm_hawb_key(n: str) -> str:
                            return re.sub(r"[^A-Z0-9]", "", (n or "").upper())

                        def _digits_only(n: str) -> str:
                            return "".join(ch for ch in (n or "") if ch.isdigit())

                        def _middle_slice(s: str, size: int) -> str:
                            if len(s) <= size:
                                return s
                            start = max(0, (len(s) - size) // 2)
                            return s[start:start + size]

                        def _hawb_variants(n: str) -> list[str]:
                            norm = _norm_hawb_key(n)
                            digits = _digits_only(norm)
                            out: list[str] = []

                            def _add(v: str):
                                if v and v not in out:
                                    out.append(v)

                            _add(norm)
                            _add(_middle_slice(norm, 8))
                            _add(_middle_slice(norm, 6))
                            if len(digits) >= 8:
                                _add(digits[-8:])
                            if len(digits) >= 6:
                                _add(digits[-6:])
                            _add(_middle_slice(digits, 8))
                            _add(_middle_slice(digits, 6))
                            return out

                        def _primary_hawb_key(n: str) -> str:
                            digits = _digits_only(n)
                            if len(digits) >= 8:
                                return digits[-8:]
                            norm = _norm_hawb_key(n)
                            if len(norm) >= 8:
                                return norm[-8:]
                            return norm

                        pdf_hawbs_unique: list[tuple[str, dict]] = []
                        pdf_seen_keys: set[str] = set()
                        for hi, hawb in enumerate(display_hawbs):
                            hawb_num_key = (hawb.get("hawb_number") or f"HAWB_{hi + 1}").strip()
                            pkey = _primary_hawb_key(hawb_num_key)
                            dedupe_key = pkey or _norm_hawb_key(hawb_num_key)
                            if dedupe_key and dedupe_key in pdf_seen_keys:
                                continue
                            if dedupe_key:
                                pdf_seen_keys.add(dedupe_key)
                            pdf_hawbs_unique.append((hawb_num_key, hawb))

                        ic_entries: list[dict] = []
                        ic_variant_index: dict[str, list[int]] = {}
                        for h in ic_hawb_list:
                            if not isinstance(h, dict):
                                continue
                            raw = _ic_num(h)
                            if not raw:
                                continue
                            idx_ic = len(ic_entries)
                            ic_entries.append({
                                "raw": raw,
                                "record": h,
                                "variants": _hawb_variants(raw),
                            })
                            for variant in ic_entries[idx_ic]["variants"]:
                                ic_variant_index.setdefault(variant, []).append(idx_ic)

                        matched_ic_idx: set[int] = set()

                        def _match_score(pdf_num: str, ic_num: str) -> int:
                            pdf_norm = _norm_hawb_key(pdf_num)
                            ic_norm = _norm_hawb_key(ic_num)
                            if not pdf_norm or not ic_norm:
                                return 0
                            if pdf_norm == ic_norm:
                                return 100
                            pdf_digits = _digits_only(pdf_norm)
                            ic_digits = _digits_only(ic_norm)
                            if len(pdf_digits) >= 8 and len(ic_digits) >= 8 and pdf_digits[-8:] == ic_digits[-8:]:
                                return 95
                            if len(pdf_digits) >= 6 and len(ic_digits) >= 6 and pdf_digits[-6:] == ic_digits[-6:]:
                                return 85
                            return 0

                        for hawb_num_key, hawb in pdf_hawbs_unique:
                            pdf_vars = _hawb_variants(hawb_num_key)
                            candidate_idxs: set[int] = set()
                            for variant in pdf_vars:
                                for idx_ic in ic_variant_index.get(variant, []):
                                    if idx_ic not in matched_ic_idx:
                                        candidate_idxs.add(idx_ic)

                            best_idx = None
                            best_score = 0
                            for idx_ic in candidate_idxs:
                                score = _match_score(hawb_num_key, ic_entries[idx_ic]["raw"])
                                if score > best_score:
                                    best_score = score
                                    best_idx = idx_ic

                            if best_idx is None:
                                for idx_ic, entry in enumerate(ic_entries):
                                    if idx_ic in matched_ic_idx:
                                        continue
                                    score = _match_score(hawb_num_key, entry["raw"])
                                    if score > best_score:
                                        best_score = score
                                        best_idx = idx_ic

                            if best_idx is not None and best_score >= 70:
                                matched_ic_idx.add(best_idx)
                                ic_label = ic_entries[best_idx]["raw"]
                                ic_hawb = ic_entries[best_idx]["record"]
                                ic_hawb_mapped = map_icargo_hawb_ibs(ic_hawb)
                                rows_h = diff_hawb(hawb, ic_hawb_mapped)
                                hawb_compare_records.append({
                                    "status": "matched",
                                    "pdf_hawb": hawb_num_key,
                                    "icargo_hawb": ic_label,
                                    "score": best_score,
                                    "rows": rows_h,
                                    "pdf_hawb_data": hawb,
                                    "icargo_hawb_data": ic_hawb,
                                    "icargo_hawb_mapped": ic_hawb_mapped,
                                })
                                match_debug_rows.append({"status": "matched", "pdf_hawb": hawb_num_key, "icargo_hawb": ic_label, "score": best_score})
                            else:
                                rows_h = diff_hawb(hawb, map_icargo_hawb_ibs({}))
                                hawb_compare_records.append({
                                    "status": "pdf_only",
                                    "pdf_hawb": hawb_num_key,
                                    "icargo_hawb": "",
                                    "score": best_score,
                                    "rows": rows_h,
                                    "pdf_hawb_data": hawb,
                                        "icargo_hawb_data": {},
                                        "icargo_hawb_mapped": {},
                                })
                                match_debug_rows.append({"status": "pdf_only", "pdf_hawb": hawb_num_key, "icargo_hawb": "", "score": best_score})

                        for idx_ic, entry in enumerate(ic_entries):
                            if idx_ic not in matched_ic_idx:
                                ic_hawb_mapped = map_icargo_hawb_ibs(entry["record"])
                                rows_h = diff_hawb({}, ic_hawb_mapped)
                                hawb_compare_records.append({
                                    "status": "icargo_only",
                                    "pdf_hawb": "",
                                    "icargo_hawb": entry["raw"],
                                    "score": 0,
                                    "rows": rows_h,
                                    "pdf_hawb_data": {},
                                    "icargo_hawb_data": entry["record"],
                                    "icargo_hawb_mapped": ic_hawb_mapped,
                                })
                                match_debug_rows.append({"status": "icargo_only", "pdf_hawb": "", "icargo_hawb": entry["raw"], "score": 0})

                        st.session_state["icargo_compare_cache"][compare_state_key] = {
                            "awb": awb_for_icargo,
                            "icargo_awb_raw": icargo_result,
                            "mawb_rows": mawb_rows,
                            "hawb_records": hawb_compare_records,
                            "match_debug_rows": match_debug_rows,
                            "hawbs_resp": hawbs_resp,
                        }
                    except Exception as e:
                        st.error(f"iCargo error: {e}")

            compare_data = st.session_state.get("icargo_compare_cache", {}).get(compare_state_key)
            if compare_data:
                editor_column_config = {
                    "field": st.column_config.TextColumn("field", disabled=True),
                    "pdf_llm": st.column_config.TextColumn("pdf_llm"),
                    "icargo": st.column_config.TextColumn("icargo", disabled=True),
                    "match": st.column_config.CheckboxColumn("match", disabled=True),
                    "apply": st.column_config.CheckboxColumn("apply"),
                }
                st.caption(f"Write target: {os.getenv('ICARGO_BASE_URL') or 'https://mac-stag-icargo.ibsplc.aero'}")
                if st.button("Clear all selections", key=f"deselect_all_{compare_state_key}"):
                    hawb_prefix = f"hawb_editor_{compare_state_key}_"
                    keys_to_clear = [
                        k for k in st.session_state.keys()
                        if k == f"mawb_editor_{compare_state_key}" or k.startswith(hawb_prefix)
                    ]
                    for k in keys_to_clear:
                        del st.session_state[k]
                    # Persist the flag (don't pop it) — data_editor only keeps a diff on
                    # top of the freshly recomputed base rows each rerun, so if we stopped
                    # forcing apply=False after one render, editing any single cell would
                    # make every other mismatched row's checkbox reappear as checked.
                    st.session_state[f"force_deselect_{compare_state_key}"] = True
                    st.rerun()
                force_deselect = st.session_state.get(f"force_deselect_{compare_state_key}", False)
                st.markdown("##### MAWB")
                mawb_rows_augmented = _augment_rows_with_post_fields(
                    compare_data.get("mawb_rows", []),
                    display_mawb,
                    MAWB_POST_EDITABLE_FIELDS,
                )
                mawb_editor_rows = _editor_rows_with_apply(
                    mawb_rows_augmented,
                    default_apply_mismatch=not force_deselect,
                )
                edited_mawb = st.data_editor(
                    mawb_editor_rows,
                    width='stretch',
                    hide_index=True,
                    disabled=["field", "icargo", "match"],
                    column_config=editor_column_config,
                    key=f"mawb_editor_{compare_state_key}",
                )
                mawb_mismatches = [r for r in compare_data.get("mawb_rows", []) if not r.get("match")]
                if not mawb_mismatches:
                    st.success("✅ MAWB — no differences!")
                else:
                    st.warning(f"⚠️ MAWB — {len(mawb_mismatches)} difference(s)")

                hawb_payload_candidates: list[dict] = []
                if compare_data.get("hawb_records"):
                    st.markdown("##### HAWBs")
                    hawbs_resp = compare_data.get("hawbs_resp")
                    if hawbs_resp is not None:
                        with st.expander("🔎 iCargo raw HAWB response", expanded=False):
                            st.json(hawbs_resp)

                    for hi, rec in enumerate(compare_data.get("hawb_records", [])):
                        status = rec.get("status")
                        label = rec.get("pdf_hawb") or rec.get("icargo_hawb") or f"HAWB_{hi+1}"
                        suffix = f" ↔ iCargo {rec.get('icargo_hawb')}" if rec.get("icargo_hawb") else ""
                        if status == "pdf_only":
                            st.markdown(f"###### {label} | PDF only")
                        elif status == "icargo_only":
                            st.markdown(f"###### {label} | iCargo only (editable)")
                        else:
                            st.markdown(f"###### {label}{suffix}")

                        hawb_source_data = rec.get("pdf_hawb_data") or rec.get("icargo_hawb_mapped") or {}

                        seeded_rows: list[dict] = []
                        for row in rec.get("rows", []):
                            row_copy = dict(row)
                            field_name = str(row_copy.get("field") or "").strip()
                            if row_copy.get("pdf_llm") in (None, "", "—") and field_name:
                                row_copy["pdf_llm"] = _to_editor_cell(hawb_source_data.get(field_name))
                            seeded_rows.append(row_copy)

                        hawb_rows_augmented = _augment_rows_with_post_fields(
                            seeded_rows,
                            hawb_source_data,
                            HAWB_POST_EDITABLE_FIELDS,
                        )
                        editor_rows = _editor_rows_with_apply(
                            hawb_rows_augmented,
                            default_apply_mismatch=(status != "icargo_only") and not force_deselect,
                        )
                        edited_hawb = st.data_editor(
                            editor_rows,
                            width='stretch',
                            hide_index=True,
                            disabled=["field", "icargo", "match"],
                            column_config=editor_column_config,
                            key=f"hawb_editor_{compare_state_key}_{hi}",
                        )

                        raw_icargo_hawb = rec.get("icargo_hawb_data")
                        if raw_icargo_hawb:
                            with st.expander(f"HAWB diagnostics: {label}", expanded=False):
                                col_rt, col_bisect = st.columns(2)
                                with col_rt:
                                    if st.button(
                                    "Round-trip test",
                                    key=f"roundtrip_{compare_state_key}_{hi}",
                                    help="Resend the record as returned by GET, without edits.",
                                    ):
                                        try:
                                            ic = ICargoIBSClient()
                                            msg = ic.save_hawbs(awb_for_icargo, [dict(raw_icargo_hawb)])
                                            st.success(f"Round-trip successful: {msg}")
                                        except Exception as e:
                                            st.error(f"Round-trip failed: {e}")
                                with col_bisect:
                                    if st.button(
                                    "Field bisection",
                                    key=f"bisect_{compare_state_key}_{hi}",
                                    help="Remove one field at a time to identify a rejected field.",
                                    ):
                                        ic = ICargoIBSClient()
                                        with st.spinner("Testing fields..."):
                                            bisect_results = _bisect_hawb_payload_fields(ic, awb_for_icargo, dict(raw_icargo_hawb))
                                        st.dataframe(
                                            [{"removed_field": k, "result": "OK" if ok else "failed", "detail": msg} for k, ok, msg in bisect_results],
                                            width='stretch',
                                        )
                                        if bisect_results and bisect_results[-1][1]:
                                            st.success(f"Suspect field: '{bisect_results[-1][0]}'. Removing it makes the POST succeed.")
                                        else:
                                            st.warning("No single field resolves the issue. Check for a missing field or combination of fields.")

                                if st.button(
                                    "Minimal payload test",
                                    key=f"minimal_{compare_state_key}_{hi}",
                                    help="Remove optional fields, then add them back one at a time if the POST succeeds.",
                                ):
                                    ic = ICargoIBSClient()
                                    with st.spinner("Testing minimal payload..."):
                                        ok, msg, minimal = _test_minimal_hawb_payload(ic, awb_for_icargo, dict(raw_icargo_hawb))
                                    if ok:
                                        st.success(msg)
                                        with st.spinner("Adding optional fields back..."):
                                            readd_results = _readd_exotic_fields_one_by_one(ic, awb_for_icargo, dict(raw_icargo_hawb), minimal)
                                        st.dataframe(
                                            [{"readded_field": k, "result": "OK" if ok2 else "failed", "detail": m} for k, ok2, m in readd_results],
                                            width='stretch',
                                        )
                                    else:
                                        st.error(f"Minimal payload test failed: {msg}")

                        hawb_edited_rows = _to_records(edited_hawb)
                        selected_fields = _selected_fields_from_rows(hawb_edited_rows)
                        edited_values = _edited_pdf_values_from_rows(hawb_edited_rows)
                        if selected_fields:
                            hawb_payload_source = (
                                rec.get("pdf_hawb_data")
                                or rec.get("icargo_hawb_mapped")
                                or ({"hawb_number": rec.get("icargo_hawb")} if rec.get("icargo_hawb") else {})
                            )
                            hawb_payload_candidates.append({
                                "hawb_data": hawb_payload_source,
                                "selected_fields": selected_fields,
                                "edited_values": edited_values,
                                "raw_icargo_hawb": rec.get("icargo_hawb_data"),
                            })

                with st.expander("HAWB match diagnostics", expanded=False):
                    st.dataframe(compare_data.get("match_debug_rows", []), width='stretch')

                mawb_edited_rows = _to_records(edited_mawb)
                selected_mawb_fields = _selected_fields_from_rows(mawb_edited_rows)
                selected_mawb_edited_values = _edited_pdf_values_from_rows(mawb_edited_rows)

                col_m, col_h, col_all = st.columns(3)
                with col_m:
                    update_master_btn = st.button("Update Master", key=f"upd_master_{compare_state_key}", width="stretch")
                with col_h:
                    update_house_btn = st.button("Update House", key=f"upd_house_{compare_state_key}", width="stretch")
                with col_all:
                    update_all_btn = st.button("Update Selected", key=f"upd_all_{compare_state_key}", type="primary", width="stretch")

                def _do_update_master() -> bool:
                    if not selected_mawb_fields:
                        st.warning("Select at least one MAWB field to update.")
                        return False
                    ic = ICargoIBSClient()
                    payload = _build_awb_update_payload(
                        compare_data.get("icargo_awb_raw") or {},
                        display_mawb,
                        selected_mawb_fields,
                        selected_mawb_edited_values,
                        awb_for_icargo,
                    )
                    msg = ic.save_awb(awb_for_icargo, payload)
                    st.success(f"✅ Master updated: {msg}")
                    return True

                def _do_update_house() -> bool:
                    if not hawb_payload_candidates:
                        st.warning("Select at least one HAWB field to update.")
                        return False
                    payload_list: list[dict] = []
                    for item in hawb_payload_candidates:
                        hawb_payload = _build_hawb_detail_payload(
                            awb_for_icargo,
                            item["hawb_data"],
                            item["selected_fields"],
                            item.get("edited_values") or {},
                            raw_icargo_hawb=item.get("raw_icargo_hawb"),
                        )
                        if hawb_payload.get("hawb"):
                            payload_list.append(hawb_payload)
                    if not payload_list:
                        st.warning("No valid HAWB to send.")
                        return False
                    ic = ICargoIBSClient()
                    msg = ic.save_hawbs(awb_for_icargo, payload_list)
                    st.success(f"✅ House updated: {msg}")
                    return True

                try:
                    if update_master_btn:
                        _do_update_master()
                    if update_house_btn:
                        _do_update_house()
                    if update_all_btn:
                        if _do_update_master():
                            _do_update_house()
                except Exception as e:
                    st.error(f"iCargo update error: {e}")
    # ── Batch download ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Batch Download")

    all_json = json.dumps(results, indent=2, default=str)
    st.download_button(
        label="Download all JSON",
        data=all_json,
        file_name=f"awbs_batch_{len(results)}.json",
        mime="application/json",
    )

    try:
        import pandas as pd
        # Flatten: one row per MAWB with hawb_count
        flat_rows = []
        for r in results:
            row = dict(r.get("mawb", r))
            row["hawb_count"] = len(r.get("hawbs", []))
            if is_zip and r.get("_pdf_name"):
                row["source_pdf"] = r["_pdf_name"]
            flat_rows.append(row)
        df = pd.DataFrame(flat_rows)
        st.download_button(
            label="Download MAWB summary CSV",
            data=df.to_csv(index=False),
            file_name=f"awbs_batch_{len(results)}.csv",
            mime="text/csv",
        )
    except Exception:
        pass
