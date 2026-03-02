# app/llm/cohere_provider.py
from __future__ import annotations
import os
import time
import httpx
import cohere

class CohereProvider:
    def __init__(self):
        api_key = os.getenv("CO_API_KEY") or os.getenv("COHERE_API_KEY")
        if not api_key:
            raise RuntimeError("Manca COHERE_API_KEY (o CO_API_KEY)")

        # Higher timeout (can be set via COHERE_TIMEOUT env var)
        t = float(os.getenv("COHERE_TIMEOUT", "120"))
        timeout = httpx.Timeout(t, connect=30.0, read=t, write=30.0, pool=30.0)
        self._httpx_client = httpx.Client(timeout=timeout)

        # Cohere ClientV2 accetta timeout + httpx_client [3](https://teamsite.msc.com/sites/OV/OPS/INF/SitePages/Upgrade-Satellite-Server.aspx?web=1)[4](https://pypi.org/project/streamlit/)
        self.client = cohere.ClientV2(api_key=api_key, timeout=t, httpx_client=self._httpx_client)

    def extract_awb_json(self, text: str) -> str:
        # IMPORTANTE: quando usi json_object, la prompt deve esplicitare "Generate a JSON..." [1](https://dnmtechs.com/fixing-tesseractnotfound-error-in-python-3-programming/)
        user_prompt = (
            "Generate a JSON object by extracting these fields from the OCR text of an Air Waybill.\n"
            "Return ONLY the JSON object (no markdown, no comments).\n\n"
            "Fields (use exactly these keys):\n"
            "- awb_number (format NNN-NNNNNNNN)\n"
            "- origin (IATA 3 letters)\n"
            "- destination (IATA 3 letters)\n"
            "- agent (string, agent name or code)\n"
            "- pieces (integer)\n"
            "- weight (number)\n"
            "- goods_description (string)\n"
            "- shipper (string)\n"
            "- consignee (string)\n"
            "- flight_number (string, e.g. CP5286 if present)\n"
            "- flight_date (string, YYYY-MM-DD if present)\n\n"
            "Rules:\n"
            "- If a value is not present in the text, set it to null.\n"
            "- Do NOT invent.\n"
            "- If weight appears like '150 KG', output weight=150.\n\n"
            f"OCR_TEXT:\n{text[:12000]}"
        )

        # JSON Schema mode: impone struttura e chiavi
        schema = {
            "type": "object",
            "properties": {
                "awb_number": {"type": ["string", "null"]},
                "origin": {"type": ["string", "null"]},
                "destination": {"type": ["string", "null"]},
                "agent": {"type": ["string", "null"]},
                "pieces": {"type": ["integer", "null"]},
                "weight": {"type": ["number", "null"]},
                "goods_description": {"type": ["string", "null"]},
                "shipper": {"type": ["string", "null"]},
                "consignee": {"type": ["string", "null"]},
                "flight_number": {"type": ["string", "null"]},
                "flight_date": {"type": ["string", "null"]},
            },
            "required": [
                "awb_number", "origin", "destination", "agent",
                "pieces", "weight", "goods_description",
                "shipper", "consignee", "flight_number", "flight_date"
            ]
        }

        last = None
        for attempt in range(3):
            try:
                res = self.client.chat(
                    model="command-r-plus-08-2024",
                    messages=[{"role": "user", "content": user_prompt}],
                    response_format={"type": "json_object", "schema": schema},  # Structured Outputs JSON Schema [1](https://dnmtechs.com/fixing-tesseractnotfound-error-in-python-3-programming/)[2](https://teamsite.msc.com/sites/OV/TR/TRA/_layouts/15/Doc.aspx?sourcedoc=%7B1E57E5A9-2CD1-460E-BED5-609F11EDB808%7D&file=MSC%20Testing%20Tool%20-%20Ready%20to%20Retest%20-%20Script.docx&action=default&mobileredirect=true&DefaultItemOpen=1)
                    temperature=0.0,
                )
                return res.message.content[0].text
            except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
                last = e
                time.sleep(0.8 * (attempt + 1))

        raise RuntimeError(f"Cohere call failed after retries: {last}")