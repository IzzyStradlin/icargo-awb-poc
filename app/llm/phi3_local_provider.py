# app/llm/phi3_local_provider.py
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import onnxruntime_genai as og

load_dotenv()

_JSON_BLOCK = re.compile(r"\{.*?\}", re.S)
_AWB_RE = re.compile(r"^\d{3}-\d{8}$")
_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _extract_json_object(text: str) -> str:
    """Estrai JSON dal testo, gestendo markdown code blocks e JSON incompleto."""
    s = (text or "").strip()
    
    # Prova a trovare JSON in markdown code blocks first
    markdown_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', s, re.S)
    if markdown_match:
        json_str = markdown_match.group(1).strip()
        # If JSON is incomplete (no closing brace), add it
        if json_str.count('{') > json_str.count('}'):
            json_str += '}' * (json_str.count('{') - json_str.count('}'))
        return json_str
    
    # Altrimenti cerca JSON direttamente
    m = _JSON_BLOCK.search(s)
    if m:
        json_str = m.group(0).strip()
        # Se incompleto, aggiungi closing braces
        if json_str.count('{') > json_str.count('}'):
            json_str += '}' * (json_str.count('{') - json_str.count('}'))
        return json_str
    
    return ""


def _build_prompt_prefix() -> str:
    # ✅ Prompt ottimizzato: LLM si concentra su campi testuali difficili
    return (
        "Extract Air Waybill (AWB) fields from OCR text. Return ONLY valid JSON.\n\n"
        "IMPORTANT RULES:\n"
        "INSTRUCTIONS:\n"
        "1. Extract ONLY: shipper, consignee, goods_description, agent, flight_number, flight_date\n"
        "2. Other fields (awb_number, origin, destination, pieces, weight): ALWAYS null\n"
        "3. CRITICAL: Return values EXACTLY AS THEY APPEAR in text. Do NOT filter, interpret, or filter.\n"
        "4. Return null only if field is completely MISSING from document.\n"
        "5. Ignore boilerplate (conditions, legal text) - extract actual data only.\n\n"
        "FIELD PATTERNS (high priority):\n"
        "shipper: First company name after 'Shipper' or 'FROM' section. Example: 'DSV S.P.A.'\n"
        "consignee: First company name after 'Consignee' or 'TO' section. Example: 'DSV AIR AND SEA LTD'\n"
        "goods_description: Text describing cargo. Example: 'Consolidation as per attached list'\n"
        "agent: Company handling shipment. Example: 'ALISCARGO AIRLINES' or 'DSV SPA'\n"
        "flight_number: Airline code+number. Example: 'CP125', 'BA456' (2 letters + digits, no spaces)\n"
        "flight_date: Date any format. Example: '01-Oct-23' or '2023-10-01'\n\n"
        "Return null only if field MISSING.\n\n"
        "{\n"
        '  "awb_number": null,\n'
        '  "origin": null,\n'
        '  "destination": null,\n'
        '  "pieces": null,\n'
        '  "weight": null,\n'
        '  "shipper": "EXTRACT_HERE_or_null",\n'
        '  "consignee": "EXTRACT_HERE_or_null",\n'
        '  "agent": "EXTRACT_HERE_or_null",\n'
        '  "goods_description": "EXTRACT_HERE_or_null",\n'
        '  "flight_number": "EXTRACT_HERE_or_null",\n'
        '  "flight_date": "EXTRACT_HERE_or_null"\n'
        "}\n\n"
        "OCR Text:\n"
    )


def _safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _get_context_length(model_dir: str) -> int:
    cfg_path = Path(model_dir) / "genai_config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return int(cfg["model"]["context_length"])


# Legal/boilerplate phrases that should be filtered out
_LEGAL_PHRASES = [
    'SHIPMENT MAY BE',
    'SUBJECT TO',
    'CONDITIONS',
    'CARRIED VIA',
    'INTERMEDIATE STOPPING',
    'AGREED',
    'HANDLING INFORMATION',
    'IT IS AGREED',
    'FOR AND ON BEHALF',
    'COMPANY',
    'CLAUSE',
]


def _is_boilerplate(text: str) -> bool:
    """Check if text contains legal boilerplate phrases."""
    if not text:
        return False
    text_upper = text.upper()
    return any(phrase in text_upper for phrase in _LEGAL_PHRASES)


def _normalize_field_value(key: str, val: Any) -> Any:
    if val is None:
        return None

    if isinstance(val, str):
        v = val.strip()
        if v == "" or v.lower() == "null":
            return None
        
        # Don't filter shipper/agent/consignee based on boilerplate - let them through
        # The rule-based system will validate them
        
        if key in ("origin", "destination"):
            return v.upper()
        if key == "awb_number":
            return v.strip()
        return v

    if key == "pieces":
        try:
            if isinstance(val, bool):
                return None
            return int(val)
        except Exception:
            return val

    if key == "weight":
        try:
            if isinstance(val, bool):
                return None
            return float(val)
        except Exception:
            return val

    return val


def _is_better_value(key: str, current: Any, candidate: Any) -> bool:
    if candidate is None:
        return False
    if current is None:
        return True

    if key == "awb_number":
        cur_ok = isinstance(current, str) and _AWB_RE.match((current or "").strip()) is not None
        cand_ok = isinstance(candidate, str) and _AWB_RE.match((candidate or "").strip()) is not None
        return (not cur_ok) and cand_ok

    if key in ("origin", "destination"):
        cur_ok = isinstance(current, str) and _IATA_RE.match((current or "").strip().upper()) is not None
        cand_ok = isinstance(candidate, str) and _IATA_RE.match((candidate or "").strip().upper()) is not None
        return (not cur_ok) and cand_ok

    return False


def _merge_partial_jsons(partials: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = [
        "awb_number", "origin", "destination", "agent", "pieces", "weight",
        "goods_description", "shipper", "consignee", "flight_number", "flight_date"
    ]
    merged: Dict[str, Any] = {k: None for k in keys}

    for p in partials:
        if not isinstance(p, dict):
            continue
        for k in keys:
            if k not in p:
                continue
            cand = _normalize_field_value(k, p.get(k))
            cur = merged.get(k)
            if _is_better_value(k, cur, cand):
                merged[k] = cand

    return merged


class Phi3LocalProvider:
    """
    DirectML è sensibile alle shape dinamiche; qui usiamo:
      - max_length fisso (total_cap) per evitare mismatch di shape su DML
      - UNA sola append_tokens(all_ids) (no continuous decoding/chat mode) [1](https://huggingface.co/docs/transformers/main_classes/tokenizer)
      - fallback a CPU in caso di errori DML (OOM o broadcasting)
    """

    def __init__(self, model_dir: Optional[str] = None):
        self.force_cpu = os.getenv("PHI3_FORCE_CPU", "0") == "1"

        self.model_dir = model_dir or os.getenv("PHI3_MODEL_DIR", "./directml")
        self.cpu_model_dir = os.getenv("PHI3_CPU_MODEL_DIR", "")

        self.max_new_tokens = int(os.getenv("PHI3_MAX_TOKENS", "128"))
        self.max_total_length = int(os.getenv("PHI3_MAX_TOTAL_LENGTH", "1024"))
        self.chunk_overlap = int(os.getenv("PHI3_CHUNK_OVERLAP", "32"))
        self.max_chunks = int(os.getenv("PHI3_MAX_CHUNKS", "6"))
        self.safety_margin = int(os.getenv("PHI3_SAFETY_MARGIN", "32"))

        self.prompt_prefix = _build_prompt_prefix()

        # Lazy init holders
        self._cpu_model = None
        self._cpu_tokenizer = None
        self._cpu_context_length = None
        self._cpu_prefix_ids = None

        # ✅ Se forzi CPU, NON caricare DML
        if self.force_cpu:
            self._ensure_cpu()
            if self._cpu_model is None:
                raise RuntimeError("PHI3_FORCE_CPU=1 ma PHI3_CPU_MODEL_DIR non è valido.")
            # usa CPU come modello principale
            self.model = self._cpu_model
            self.tokenizer = self._cpu_tokenizer
            self.context_length = self._cpu_context_length
            self.prefix_ids = self._cpu_prefix_ids
            return

        # ✅ Altrimenti carica DML normalmente
        self.model = og.Model(self.model_dir)
        self.tokenizer = og.Tokenizer(self.model)
        self.context_length = _get_context_length(self.model_dir)
        self.prefix_ids = self.tokenizer.encode(self.prompt_prefix)

    def _ensure_cpu(self):
        if not self.cpu_model_dir:
            return
        if self._cpu_model is None:
            self._cpu_model = og.Model(self.cpu_model_dir)
            self._cpu_tokenizer = og.Tokenizer(self._cpu_model)
            self._cpu_context_length = _get_context_length(self.cpu_model_dir)
            self._cpu_prefix_ids = self._cpu_tokenizer.encode(self.prompt_prefix)

    def _chunk_ocr_ids(self, ocr_text: str) -> List[List[int]]:
        ocr_text = (ocr_text or "").strip()
        if not ocr_text:
            return [[]]

        total_cap = min(self.context_length, self.max_total_length)
        # ✅ Riduci il budget dei token OCR per modelli piccoli (quantizzati)
        # Lasciamo spazio: prefix + output + margine significativo
        budget = total_cap - self.max_new_tokens - len(self.prefix_ids) - self.safety_margin - 100
        if budget <= 0:
            return [[]]

        ocr_ids = self.tokenizer.encode(ocr_text)
        # If OCR is too long, limit to 300 tokens maximum
        if len(ocr_ids) > 300:
            ocr_ids = ocr_ids[:300]
        
        if len(ocr_ids) <= budget:
            return [ocr_ids]

        chunks: List[List[int]] = []
        step = max(1, budget - self.chunk_overlap)

        for start in range(0, len(ocr_ids), step):
            end = min(len(ocr_ids), start + budget)
            chunks.append(ocr_ids[start:end])
            if end >= len(ocr_ids):
                break

        return chunks

    def _run_once(self, model: og.Model, tokenizer: og.Tokenizer, context_len: int, prefix_ids: List[int], chunk_ids: List[int]) -> Dict[str, Any]:
        """Usa append_tokens con proper list conversion e limiti di input."""
        try:
            # ✅ FIX: Converti numpy arrays a liste prima di concatenare
            prefix_list = list(prefix_ids) if not isinstance(prefix_ids, list) else prefix_ids
            chunk_list = list(chunk_ids) if not isinstance(chunk_ids, list) else chunk_ids
            
            # Ricombina token come liste
            all_ids = prefix_list + chunk_list
            
            # Calcola limite rigido in base a contesto disponibile
            total_cap = min(context_len, self.max_total_length)
            # ✅ Aumenta token di output per JSON completo (almeno 256 token per JSON valido)
            # Non limitare a self.max_new_tokens per JSON extraction
            max_gen_tokens = max(256, total_cap - len(all_ids) - 50)
            
            # ✅ NUOVO: Limita aggressivamente input per modelli quantizzati
            # Max 350 token input totale per evitare che il modello si blocchi
            if len(all_ids) > 350:
                # Taglia il chunk per stare sotto 350
                max_input = 350
                available_for_chunk = max_input - len(prefix_list)
                if available_for_chunk > 0:
                    all_ids = prefix_list + chunk_list[:available_for_chunk]
                else:
                    # Prompt is also too long, reduce that
                    all_ids = prefix_list[:max_input]
            
            # Crea i parameters
            params = og.GeneratorParams(model)
            params.set_search_options(
                do_sample=False,
                temperature=0.0,
                max_length=len(all_ids) + max_gen_tokens,  # Total sequence length
                past_present_share_buffer=False,
            )
            
            # ✅ CORRETTO: Usa append_tokens con lista (non numpy array)
            generator = og.Generator(model, params)
            generator.append_tokens(all_ids)
            
            out_tokens: List[int] = []
            for i in range(max_gen_tokens):
                if generator.is_done():
                    break
                generator.generate_next_token()
                next_token = generator.get_next_tokens()[0]
                out_tokens.append(next_token)
            
            generated_ids = out_tokens
            
            if not generated_ids:
                return {}
                
            decoded = tokenizer.decode(generated_ids)
            json_text = _extract_json_object(decoded)
            result = _safe_json_loads(json_text)
            
            return result if result else {}
            
        except Exception as e:
            error_msg = str(e)
            # If it's a shape/broadcast error, return empty
            if any(x in error_msg.lower() for x in ["shape", "broadcast", "dimension"]):
                return {}
            # Altrimenti re-raise per debugging
            raise

    def _generate_json_for_tokens(self, chunk_ids: List[int]) -> Dict[str, Any]:
        if self.force_cpu:
            self._ensure_cpu()
            if self._cpu_model is None:
                raise RuntimeError("PHI3_FORCE_CPU=1 ma PHI3_CPU_MODEL_DIR non è configurato o non è valido.")
            return self._run_once(self._cpu_model, self._cpu_tokenizer, self._cpu_context_length, self._cpu_prefix_ids, chunk_ids)

        # Prova DML (normale)
        try:
            return self._run_once(self.model, self.tokenizer, self.context_length, self.prefix_ids, chunk_ids)
        except Exception as e:
            msg = str(e)

            # Se DML fallisce (OOM o broadcast mismatch), fai fallback a CPU
            if (
                "8007000E" in msg
                or "Not enough memory resources" in msg
                or "could not be broadcast together" in msg
                or "DmlFusedNode" in msg
            ):
                self._ensure_cpu()
                if self._cpu_model is None:
                    # se non hai configurato PHI3_CPU_MODEL_DIR, rilancio l'errore originale
                    raise

                return self._run_once(
                    self._cpu_model,
                    self._cpu_tokenizer,
                    self._cpu_context_length,
                    self._cpu_prefix_ids,
                    chunk_ids,
                )
            raise

    def _has_enough_fields(self, merged: Dict[str, Any]) -> bool:
        must = ["awb_number", "origin", "destination"]
        if not all(merged.get(k) for k in must):
            return False
        optional = ["pieces", "weight", "shipper", "consignee", "flight_number", "flight_date", "agent"]
        found = sum(1 for k in optional if merged.get(k) is not None)
        return found >= 2

    def extract_awb_json(self, text: str) -> str:
        """Estratto JSON dal testo OCR usando LLM locale."""
        ocr_text = text or ""
        chunks_ids = self._chunk_ocr_ids(ocr_text)

        merged = {
            "awb_number": None, "origin": None, "destination": None, "agent": None,
            "pieces": None, "weight": None, "goods_description": None,
            "shipper": None, "consignee": None, "flight_number": None, "flight_date": None
        }

        for ch_ids in chunks_ids[: self.max_chunks]:
            partial = self._generate_json_for_tokens(ch_ids)
            merged = _merge_partial_jsons([merged, partial])
            if self._has_enough_fields(merged):
                break

        return json.dumps(merged, ensure_ascii=False)