"""Tests for multi-AWB PDF extraction."""
import pytest
from app.extraction.awb_document_splitter import AwbDocumentSplitter
from app.extraction.awb_document_presplitter import AwbDocumentPreSplitter
from app.interpretation.awb_field_detector import AwbFieldDetector
from app.interpretation.awb_normalizer import AwbNormalizer
from app.interpretation.awb_number import extract_msc_awbs


class TestAwbDocumentSplitter:
    def test_single_awb(self):
        text = '''
        233-12345678
        SHIPPER: Company A
        CONSIGNEE: Company B
        ORIGIN: MXP
        DESTINATION: FCO
        PIECES: 5
        WEIGHT: 100
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] == '233-12345678'
        assert 'SHIPPER' in docs[0]['text']
    
    def test_multiple_awbs(self):
        text = '''
        233-12345678
        SHIPPER: Company A
        CONSIGNEE: Company B
        ORIGIN: MXP
        DESTINATION: FCO
        
        233-87654321
        SHIPPER: Company C
        CONSIGNEE: Company D
        ORIGIN: FCO
        DESTINATION: HKG
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 2
        assert docs[0]['awb_number'] == '233-12345678'
        assert docs[1]['awb_number'] == '233-87654321'
        assert 'Company A' in docs[0]['text']
        assert 'Company C' in docs[1]['text']
    
    def test_no_awb(self):
        text = "Some random text without AWB numbers"
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        
        assert len(docs) == 1
        assert docs[0]['awb_number'] is None
    
    def test_filter_by_prefix(self):
        text = '''
        233-12345678
        Data A
        
        234-87654321
        Data B
        '''
        splitter = AwbDocumentSplitter()
        docs = splitter.split_pdf_into_awb_documents(text)
        filtered = splitter.filter_documents_by_prefix(docs, prefix="233")
        
        assert len(filtered) == 1
        assert filtered[0]['awb_number'] == '233-12345678'


class TestMultiAwbFieldDetector:
    def test_extract_all(self):
        texts = [
            "233-12345678\nSHIPPER: Company A\nCONSIGNEE: Company B",
            "233-87654321\nSHIPPER: Company C\nCONSIGNEE: Company D"
        ]
        detector = AwbFieldDetector()
        results = detector.extract_all(texts)
        
        assert len(results) == 2
        assert results[0].data.awb_number == '233-12345678'
        assert results[1].data.awb_number == '233-87654321'


class TestMultiAwbNormalizer:
    def test_normalize_batch(self):
        from app.interpretation.awb_schema import AwbData
        
        data1 = AwbData(
            awb_prefix="233",
            awb_serial="12345678",
            origin="mxp",
            destination="fco"
        )
        data2 = AwbData(
            awb_prefix="234",
            awb_serial="87654321",
            origin="FCO",
            destination="HKG"
        )
        
        normalizer = AwbNormalizer()
        results = normalizer.normalize_batch([data1, data2])
        
        assert len(results) == 2
        assert results[0].origin == "MXP"
        assert results[1].origin == "FCO"


class TestMscAwbRecovery:
    def test_extract_msc_awb_with_split_prefix(self):
        text = "23 3- 10333750\nShipper's Name and Address Not Negotiable"

        assert extract_msc_awbs(text) == ["233-10333750"]

    def test_extract_msc_awb_with_airport_code_noise(self):
        text = "233IMXP|10146824 233-10146824"

        assert extract_msc_awbs(text)[0] == "233-10146824"

    def test_extract_msc_awb_with_spaced_serial(self):
        text = "233- 1018 3235 N° STT: 38000043055862 233-1018 3235"

        assert "233-10183235" in extract_msc_awbs(text)

    def test_extract_msc_awb_with_airwaybill_header_noise(self):
        text = "233 | MXP | 10308793 es , 233 / 10308793"

        assert extract_msc_awbs(text)[0] == "233-10308793"

    def test_enrich_document_awb_from_whole_block(self):
        page_texts = {
            1: (
                "103: Q 922-103 0\n"
                "Shipper's Name and Address Not Negotiable\n"
                "23 3- 10333750\n"
                "other OCR text"
            )
        }
        docs = [
            {
                "start_page": 1,
                "end_page": 1,
                "page_count": 1,
                "is_mawb_start": True,
                "awb_number": None,
            }
        ]

        presplitter = AwbDocumentPreSplitter()
        presplitter._enrich_documents_with_awbs(docs, page_texts)

        assert docs[0]["awb_number"] == "233-10333750"
