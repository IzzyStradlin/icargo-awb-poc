# app/ingestion/pdf_ingestor.py
from typing import BinaryIO, Union
from pathlib import Path

class PDFIngestor:
    """Handles PDF file input from path or stream."""

    def from_path(self, path: Union[str, Path]) -> bytes:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")
        return p.read_bytes()

    def from_stream(self, stream: BinaryIO) -> bytes:
        return stream.read()