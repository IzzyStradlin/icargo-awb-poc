# tests/unit/test_awb_field_detector.py
from app.interpretation.awb_field_detector import AwbFieldDetector

def test_awb_regex_basic():
    txt = "AWB 123-45678901 FROM MXP TO JFK PCS 5 WT 100.5"
    res = AwbFieldDetector().extract(txt)
    assert res.data.awb_prefix == "123"
    assert res.data.awb_serial == "45678901"
    assert res.data.origin == "MXP"
    assert res.data.destination == "JFK"