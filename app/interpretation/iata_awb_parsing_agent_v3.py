"""
IATA AWB Parsing Agent v3 - Label-Based Extraction

This is the corrected version that uses IATA standard field labels
for extraction instead of arbitrary sections.

Key improvements:
- Searches for specific IATA field labels in the text
- Extracts text blocks between known labels
- Handles misaligned OCR better
- Much more accurate for standard IATA forms
- Includes Chargeable Weight support
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

from .iata_awb_label_extractor import IataAwbLabelExtractor, LabeledFieldExtraction
from .awb_schema import AwbData, AwbExtractionResult, AwbFieldConfidence


@dataclass
class ExtractionQualityV3:
    """Quality metrics for label-based extraction."""
    overall_confidence: float
    fields_extracted: Dict[str, float]  # field -> confidence
    fields_missing: list
    labels_found: Dict[str, bool]  # field -> was label found
    extraction_notes: list


class IataAwbParsingAgentV3:
    """
    Main orchestrator for IATA AWB parsing using label-based extraction.
    
    This version is specifically designed for IATA standard Air Waybill forms
    and extracts fields by looking for their standard IATA labels rather than
    trying to identify arbitrary sections.
    """

    def __init__(self):
        """Initialize the IATA label-based parsing agent."""
        self.label_extractor = IataAwbLabelExtractor()

    def parse(self, text: str, debug: bool = False) -> AwbExtractionResult:
        """
        Parse IATA AWB document using label-based extraction.
        
        Args:
            text: OCR-extracted AWB document text
            debug: If True, print detailed debug information
            
        Returns:
            Complete extraction result with all fields and confidence scores
        """
        if debug:
            print("\n[IATA AWB v3 - Label-Based Extraction]")
            print("="*70)
        
        # Extract all fields using IATA labels
        extracted_fields = self.label_extractor.extract_all_fields(text)
        
        if debug:
            print("\nExtracted Fields:")
            for field_name, extraction in extracted_fields.items():
                if isinstance(extraction, LabeledFieldExtraction):
                    print(f"  {field_name:20s}: {extraction.value} (conf: {extraction.confidence:.0%}, label_found: {extraction.label_found})")
        
        # Build AwbData from extractions
        awb_data = self._build_awb_data(extracted_fields)
        
        # Build confidence scores
        confidences = self._build_confidences(extracted_fields)
        
        # Calculate quality metrics
        quality = self._calculate_quality(extracted_fields, awb_data)
        
        if debug:
            print(f"\nQuality Assessment:")
            print(f"  Overall Confidence: {quality.overall_confidence:.0%}")
            print(f"  Fields Extracted: {len(quality.fields_extracted)}")
            print(f"  Fields Missing: {quality.fields_missing}")
            for note in quality.extraction_notes:
                print(f"  - {note}")
        
        result = AwbExtractionResult(
            data=awb_data,
            confidences=confidences,
            raw_text=text
        )
        
        return result

    def _build_awb_data(self, extracted_fields: Dict[str, any]) -> AwbData:
        """
        Build AwbData object from extracted fields.
        """
        data = AwbData()
        
        # AWB Number (split into prefix and serial)
        awb_extraction = extracted_fields.get('awb_number')
        if awb_extraction and awb_extraction.value:
            awb_str = str(awb_extraction.value)
            if '-' in awb_str:
                parts = awb_str.split('-')
                data.awb_prefix = parts[0]
                data.awb_serial = parts[1]
        
        # Text fields (extract .value from LabeledFieldExtraction)
        shipper_extraction = extracted_fields.get('shipper')
        if shipper_extraction and shipper_extraction.value:
            data.shipper = shipper_extraction.value
        
        consignee_extraction = extracted_fields.get('consignee')
        if consignee_extraction and consignee_extraction.value:
            data.consignee = consignee_extraction.value
        
        agent_extraction = extracted_fields.get('agent')
        if agent_extraction and agent_extraction.value:
            data.agent = agent_extraction.value
        
        origin_extraction = extracted_fields.get('origin')
        if origin_extraction and origin_extraction.value:
            data.origin = origin_extraction.value
        
        destination_extraction = extracted_fields.get('destination')
        if destination_extraction and destination_extraction.value:
            data.destination = destination_extraction.value
        
        # Numeric fields
        pieces_extraction = extracted_fields.get('pieces')
        if pieces_extraction and pieces_extraction.value:
            data.pieces = int(pieces_extraction.value) if isinstance(pieces_extraction.value, (int, str)) else pieces_extraction.value
        
        weight_extraction = extracted_fields.get('gross_weight')
        if weight_extraction and weight_extraction.value:
            data.weight = float(weight_extraction.value) if isinstance(weight_extraction.value, (int, float, str)) else weight_extraction.value
        
        # NEW: Chargeable Weight (billing weight)
        chargeable_weight_extraction = extracted_fields.get('chargeable_weight')
        if chargeable_weight_extraction and chargeable_weight_extraction.value:
            data.chargeable_weight = float(chargeable_weight_extraction.value) if isinstance(chargeable_weight_extraction.value, (int, float, str)) else chargeable_weight_extraction.value
        
        # Description
        goods_extraction = extracted_fields.get('goods_description')
        if goods_extraction and goods_extraction.value:
            data.goods_description = goods_extraction.value
        
        # Flight info
        flight_extraction = extracted_fields.get('flight_number')
        if flight_extraction and flight_extraction.value:
            data.flight_no = flight_extraction.value
        
        flight_date_extraction = extracted_fields.get('flight_date')
        if flight_date_extraction and flight_date_extraction.value:
            data.flight_date = flight_date_extraction.value
        
        return data

    def _build_confidences(self, extracted_fields: Dict[str, any]) -> list:
        """
        Build list of AwbFieldConfidence objects.
        """
        confidences = []
        
        for field_name, extraction in extracted_fields.items():
            if not isinstance(extraction, LabeledFieldExtraction):
                continue
            
            if extraction.value is not None:
                # Map internal field names to external
                external_name = field_name
                if field_name == 'chargeable_weight':
                    external_name = 'chargeable_weight'  # NEW field
                
                confidences.append(AwbFieldConfidence(
                    field=external_name,
                    value=str(extraction.value),
                    confidence=extraction.confidence
                ))
        
        return confidences

    def _calculate_quality(self, extracted_fields: Dict[str, any], data: AwbData) -> ExtractionQualityV3:
        """
        Calculate quality metrics for the extraction.
        """
        fields_extracted = {}
        fields_missing = []
        labels_found = {}
        
        for field_name, extraction in extracted_fields.items():
            if not isinstance(extraction, LabeledFieldExtraction):
                continue
            
            labels_found[field_name] = extraction.label_found
            
            if extraction.value is not None:
                fields_extracted[field_name] = extraction.confidence
            else:
                if field_name not in ['flight_date', 'chargeable_weight']:  # Optional fields
                    fields_missing.append(field_name)
        
        # Calculate overall confidence
        if fields_extracted:
            overall_confidence = sum(fields_extracted.values()) / len(fields_extracted)
        else:
            overall_confidence = 0.0
        
        # Generate notes
        notes = []
        
        required_fields = {'awb_number', 'shipper', 'consignee', 'origin', 'destination'}
        extracted_required = {f for f in required_fields if f in fields_extracted}
        
        if extracted_required == required_fields:
            notes.append("All critical fields extracted")
        else:
            missing_req = required_fields - extracted_required
            notes.append(f"Missing critical fields: {missing_req}")
        
        if overall_confidence >= 0.90:
            notes.append("Extraction quality is EXCELLENT")
        elif overall_confidence >= 0.75:
            notes.append("Extraction quality is GOOD")
        elif overall_confidence >= 0.60:
            notes.append("Extraction quality is FAIR - manual verification recommended")
        else:
            notes.append("Extraction quality is POOR - manual review required")
        
        return ExtractionQualityV3(
            overall_confidence=overall_confidence,
            fields_extracted=fields_extracted,
            fields_missing=fields_missing,
            labels_found=labels_found,
            extraction_notes=notes
        )
