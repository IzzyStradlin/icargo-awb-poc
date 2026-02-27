# app/interpretation/awb_schema.py
from pydantic import BaseModel, Field, validator
from typing import Optional

class AwbData(BaseModel):
    awb_prefix: Optional[str] = Field(None, description="IATA 3-digit prefix")
    awb_serial: Optional[str] = Field(None, description="8-digit serial")
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    agent: Optional[str] = None  # Client/customer (often same as shipper)
    origin: Optional[str] = None
    destination: Optional[str] = None
    pieces: Optional[int] = None
    weight: Optional[float] = None
    goods_description: Optional[str] = None
    flight_no: Optional[str] = None
    flight_date: Optional[str] = None  # ISO date in PoC

    @property
    def awb_number(self) -> Optional[str]:
        if self.awb_prefix and self.awb_serial:
            return f"{self.awb_prefix}-{self.awb_serial}"
        return None

class AwbFieldConfidence(BaseModel):
    field: str
    value: Optional[str]
    confidence: float = 0.0

class AwbExtractionResult(BaseModel):
    data: AwbData
    confidences: list[AwbFieldConfidence] = []
    raw_text: str = ""