# app/ingestion/email_ingestor.py
from typing import List, Tuple, Optional
from email import policy
from email.parser import BytesParser

class EmailIngestResult:
    def __init__(self, subject: str, body_text: str, attachments: List[Tuple[str, bytes]]):
        self.subject = subject
        self.body_text = body_text
        self.attachments = attachments  # (filename, bytes)

class EmailIngestor:
    """Parsing file .eml locale per PoC (IMAP out-of-scope PoC)."""

    def parse_eml(self, raw_bytes: bytes) -> EmailIngestResult:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        subject = msg.get("subject", "")
        body_text = self._get_body_text(msg)
        attachments = self._get_attachments(msg)
        return EmailIngestResult(subject, body_text, attachments)

    def _get_body_text(self, msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        return part.get_content()
                    except Exception:
                        continue
        else:
            return msg.get_content()
        return ""

    def _get_attachments(self, msg) -> List[Tuple[str, bytes]]:
        files: List[Tuple[str, bytes]] = []
        for part in msg.walk():
            filename = part.get_filename()
            if filename and part.get_content_disposition() == "attachment":
                files.append((filename, part.get_payload(decode=True)))
        return files