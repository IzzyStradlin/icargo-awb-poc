# app/pipelines/run_from_email.py
from pathlib import Path
from ..ingestion.email_ingestor import EmailIngestor
from ..extraction.email_text_extractor import EmailTextExtractor
from ..interpretation.awb_field_detector import AwbFieldDetector
from ..interpretation.awb_normalizer import AwbNormalizer

def run(eml_path: str):
    raw = Path(eml_path).read_bytes()
    ing = EmailIngestor().parse_eml(raw)
    text = EmailTextExtractor().extract_text(ing.body_text)
    result = AwbFieldDetector().extract(text)
    data = AwbNormalizer().normalize(result.data)
    print("Subject:", ing.subject)
    print("AWB:", data.dict())
    print("Attachments:", [name for name, _ in ing.attachments])

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m app.pipelines.run_from_email <path_to_eml>")
    else:
        run(sys.argv[1])