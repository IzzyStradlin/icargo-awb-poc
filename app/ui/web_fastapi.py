# app/ui/web_fastapi.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from ..ingestion.pdf_ingestor import PDFIngestor
from ..extraction.pdf_text_extractor import PDFTextExtractor
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer
from ..integration.awb_repository import AwbRepository
from ..comparison.awb_diff_engine import AwbDiffEngine
from typing import List, Optional
from ..extraction.awb_document_splitter import AwbDocumentSplitter

app = FastAPI(title="iCargo AWB PoC API")

class UpdatePayload(BaseModel):
    awb_prefix: str
    awb_serial: str
    updates: dict

@app.post("/extract/awb-from-pdf")
async def extract_awb_from_pdf(
    file: UploadFile = File(...),
    filter_prefix: Optional[str] = Query(None, description="Filter to specific AWB prefix (e.g., '233')")
):
    """Extract multiple AWBs from PDF."""
    if file.content_type not in ("application/pdf",):
        raise HTTPException(status_code=400, detail="PDF required")
    
    raw = await file.read()
    
    # Extract text
    text = PDFTextExtractor().extract_text(raw)[0]
    
    # Split into individual AWB documents
    splitter = AwbDocumentSplitter()
    documents = splitter.split_pdf_into_awb_documents(text)
    
    # Optional: filter by prefix
    if filter_prefix:
        documents = splitter.filter_documents_by_prefix(documents, prefix=filter_prefix)
    
    # Extract all AWBs
    doc_texts = [doc['text'] for doc in documents]
    extraction_results = AwbFieldDetector().extract_all(doc_texts)
    
    # Normalize and prepare response
    normalizer = AwbNormalizer()
    repo = AwbRepository()
    diff_engine = AwbDiffEngine()
    
    extracted_list = []
    diffs_list = []
    
    for result in extraction_results:
        normalized = normalizer.normalize(result.data)
        extracted_list.append({
            "awb_data": normalized.dict(),
            "confidences": [c.dict() for c in result.confidences]
        })
        
        # Generate diff if AWB number is valid
        if normalized.awb_prefix and normalized.awb_serial:
            system_awb = repo.get_awb(normalized.awb_prefix, normalized.awb_serial)
            diff = diff_engine.diff(normalized.dict(), system_awb)
            diffs_list.append({
                "awb_number": normalized.awb_number,
                "diff": diff,
                "extracted": normalized.dict(),
                "system": system_awb,
            })
    
    return {
        "count": len(extracted_list),
        "extracted_awbs": extracted_list,
        "diffs": diffs_list,
    }

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