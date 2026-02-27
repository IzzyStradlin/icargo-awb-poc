# tests/unit/test_awb_diff_engine.py
from app.comparison.awb_diff_engine import AwbDiffEngine

def test_diff_basic():
    extracted = {"origin": "MXP", "destination": "JFK"}
    system = {"origin": "MXP", "destination": "EWR"}
    diff = AwbDiffEngine().diff(extracted, system)
    assert any(d["field"] == "destination" and d["match"] is False for d in diff)