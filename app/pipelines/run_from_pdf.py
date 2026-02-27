# app/pipelines/run_from_pdf.py
from pathlib import Path
from ..ingestion.pdf_ingestor import PDFIngestor
from ..extraction.pdf_text_extractor import PDFTextExtractor
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer
from ..integration.awb_repository import AwbRepository
from ..comparison.awb_diff_engine import AwbDiffEngine

def run(pdf_path: str):
    raw = PDFIngestor().from_path(pdf_path)
    text, _ = PDFTextExtractor().extract_text(raw)
    result = AwbFieldDetector().extract(text)
    data = AwbNormalizer().normalize(result.data)

    if not (data.awb_prefix and data.awb_serial):
        print("AWB non rilevata.")
        return

    repo = AwbRepository()
    system = repo.get_awb(data.awb_prefix, data.awb_serial)
    diff = AwbDiffEngine().diff(data.dict(), system)
    print("Estratto:", data.dict())
    print("System:", system)
    print("Diff:", diff)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m app.pipelines.run_from_pdf <path_to_pdf>")
    else:
        run(sys.argv[1])