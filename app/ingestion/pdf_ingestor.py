# app/ingestion/pdf_ingestor.py
from typing import BinaryIO, Union
from pathlib import Path

class PDFIngestor:
    """Gestisce l'input di file PDF da path o stream."""

    def from_path(self, path: Union[str, Path]) -> bytes:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")
        return p.read_bytes()

    def from_stream(self, stream: BinaryIO) -> bytes:
        return stream.read()