# app/interpretation/awb_schema.py
from pydantic import BaseModel, Field, validator
from typing import Optional

class AwbData(BaseModel):
    awb_prefix: Optional[str] = Field(None, description="IATA 3-digit prefix")
    awb_serial: Optional[str] = Field(None, description="8-digit serial")
    shipper: Optional[str] = None
    shipper_address: Optional[str] = None  # Full address of shipper
    consignee: Optional[str] = None
    consignee_address: Optional[str] = None  # Full address of consignee
    agent: Optional[str] = None  # Client/customer (often same as shipper)
    agent_address: Optional[str] = None  # Full address of issuing agent
    notify_party: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    pieces: Optional[int] = None
    weight: Optional[float] = None  # Gross weight in kg
    chargeable_weight: Optional[float] = None  # Chargeable weight in kg
    volume: Optional[float] = None  # Volume in CBM / m³
    dimensions: Optional[str] = None  # Package dimensions free text
    rate: Optional[float] = None          # Rate/Charge per kg
    total_charge: Optional[float] = None  # Total charges
    currency: Optional[str] = None
    goods_description: Optional[str] = None
    hs_code: Optional[str] = None
    special_handling: Optional[str] = None
    declared_value_carriage: Optional[str] = None
    declared_value_customs: Optional[str] = None
    flight_no: Optional[str] = None
    flight_date: Optional[str] = None  # ISO date

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