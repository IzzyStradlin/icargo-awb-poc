# app/extraction/email_text_extractor.py
from typing import List, Tuple
from bs4 import BeautifulSoup

class EmailTextExtractor:
    def extract_text(self, body_text: str) -> str:
        """Se HTML → testo, altrimenti passa-through."""
        if "<html" in body_text.lower():
            soup = BeautifulSoup(body_text, "lxml")
            return soup.get_text(separator="\n")
        return body_text