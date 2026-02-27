# app/ui/web_fastapi.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from ..ingestion.pdf_ingestor import PDFIngestor
from ..extraction.pdf_text_extractor import PDFTextExtractor
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer
from ..integration.awb_repository import AwbRepository
from ..comparison.awb_diff_engine import AwbDiffEngine

app = FastAPI(title="iCargo AWB PoC API")

class UpdatePayload(BaseModel):
    awb_prefix: str
    awb_serial: str
    updates: dict

@app.post("/extract/awb-from-pdf")
async def extract_awb_from_pdf(file: UploadFile = File(...)):
    if file.content_type not in ("application/pdf",):
        raise HTTPException(status_code=400, detail="PDF required")
    raw = await file.read()

    text = PDFTextExtractor().extract_text(raw)[0]
    result = AwbFieldDetector().extract(text)
    normalized = AwbNormalizer().normalize(result.data)
    return {"extracted": normalized.dict(), "confidences": [c.dict() for c in result.confidences]}

@app.get("/icargo/awb/{prefix}/{serial}")
def get_icargo_awb(prefix: str, serial: str):
    data = AwbRepository().get_awb(prefix, serial)
    return data

@app.post("/diff/awb")
def diff_awb(payload: UpdatePayload):
    repo = AwbRepository()
    system = repo.get_awb(payload.awb_prefix, payload.awb_serial)
    diff = AwbDiffEngine().diff(payload.updates, system)
    return {"diff": diff}

@app.patch("/icargo/awb")
def update_icargo_awb(payload: UpdatePayload):
    repo = AwbRepository()
    updated = repo.update_awb(payload.awb_prefix, payload.awb_serial, payload.updates)
    return {"updated": updated}