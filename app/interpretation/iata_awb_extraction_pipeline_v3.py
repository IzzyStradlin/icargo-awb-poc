"""
IATA AWB Extraction Pipeline v3 - Label-Based (CORRECTED VERSION)

This is the production-ready extraction pipeline that uses IATA standard
field label recognition instead of arbitrary section detection.

This version fixes the issues with v2:
✓ Correctly extracts Shipper (company name only, not address)
✓ Correctly extracts Consignee (company name only, not address)
✓ Correctly extracts Agent (from "Issuing Carriers Agent Name and City")
✓ Adds Chargeable Weight support
✓ Better flight number extraction
✓ Much more accurate for standard IATA forms

Usage:
    from app.interpretation.iata_awb_extraction_pipeline_v3 import IataAwbExtractionPipeline
    
    pipeline = IataAwbExtractionPipeline()
    result = pipeline.extract(ocr_text, debug=True)
    
    print(result.data.awb_number)
    print(result.data.shipper)
    print(result.data.consignee)
"""

from typing import Dict, Any, Optional, List
import logging

from .iata_awb_parsing_agent_v3 import IataAwbParsingAgentV3
from .awb_schema import AwbExtractionResult

logger = logging.getLogger(__name__)


class IataAwbExtractionPipeline:
    """
    Production-ready IATA AWB extraction using label-based field recognition.
    
    This pipeline:
    1. Recognizes IATA standard field labels in OCR text
    2. Extracts text blocks for each field
    3. Cleans and parses extracted values
    4. Validates data types
    5. Generates quality assessment
    
    Much more accurate than section-based approach because:
    - IATA forms have standard field label names
    - Once we find the label, we know what follows
    - Handles OCR artifacts much better
    """

    def __init__(self):
        """Initialize the IATA pipeline."""
        self.agent = IataAwbParsingAgentV3()

    def extract(
        self,
        text: str,
        debug: bool = False
    ) -> AwbExtractionResult:
        """
        Extract AWB data from OCR-extracted text using IATA label-based approach.
        
        Args:
            text: OCR-extracted AWB document text
            debug: If True, print detailed debug information about each extraction
            
        Returns:
            AwbExtractionResult containing:
            - data: AwbData with all extracted fields
            - confidences: List of confidence scores per field
            - raw_text: Original OCR text for reference
            
        Example:
            >>> pipeline = IataAwbExtractionPipeline()
            >>> result = pipeline.extract(ocr_text, debug=True)
            >>> print(f"Shipper: {result.data.shipper}")
            >>> print(f"Consignee: {result.data.consignee}")
            >>> print(f"Agent: {result.data.agent}")
            >>> print(f"Weight: {result.data.weight} kg")
        """
        try:
            if debug:
                logger.info("Starting IATA AWB extraction (v3 - label-based)")
                logger.info(f"OCR text length: {len(text)} characters")
            
            # Run the label-based parsing agent
            extraction_result = self.agent.parse(text, debug=debug)
            
            if debug:
                logger.info("Extraction completed successfully")
                self._log_extraction_summary(extraction_result)
            
            return extraction_result
        
        except Exception as e:
            logger.error(f"Error during AWB extraction: {e}", exc_info=True)
            # Return empty result on error
            return self._empty_result(text)

    def extract_multiple(
        self,
        texts: List[str],
        debug: bool = False
    ) -> List[AwbExtractionResult]:
        """
        Extract AWB data from multiple OCR text blocks.
        
        Useful when a single PDF contains multiple AWB documents.
        
        Args:
            texts: List of OCR-extracted text blocks
            debug: If True, print debug information
            
        Returns:
            List of AwbExtractionResult objects
        """
        results = []
        for i, text in enumerate(texts):
            if debug:
                logger.info(f"Processing document {i+1}/{len(texts)}")
            result = self.extract(text, debug=debug)
            results.append(result)
        
        return results

    def get_extraction_quality_report(self, result: AwbExtractionResult) -> Dict[str, Any]:
        """
        Generate a quality report for an extraction result.
        
        Returns metrics about extraction reliability:
        - Overall confidence score (0-1)
        - Which fields have high/low confidence
        - Which critical fields are missing
        - Recommendations for manual review
        
        Args:
            result: AwbExtractionResult from extract()
            
        Returns:
            Dictionary with quality metrics and recommendations
        """
        if not result.confidences:
            return {
                'status': 'FAILED',
                'overall_confidence': 0.0,
                'recommendation': 'Extraction failed - manual review required',
                'details': 'No fields were successfully extracted'
            }
        
        # Calculate statistics
        avg_confidence = sum(c.confidence for c in result.confidences) / len(result.confidences)
        
        high_conf_fields = [c.field for c in result.confidences if c.confidence >= 0.85]
        low_conf_fields = [c.field for c in result.confidences if c.confidence < 0.60]
        
        # Check for critical fields
        critical_fields = {'awb_number', 'shipper', 'consignee', 'origin', 'destination'}
        extracted_critical = {c.field for c in result.confidences if c.field in critical_fields}
        missing_critical = critical_fields - extracted_critical
        
        # Determine status and recommendation
        if avg_confidence >= 0.90 and not missing_critical:
            status = 'EXCELLENT'
            recommendation = 'Safe to use - high confidence extraction'
        elif avg_confidence >= 0.75 and not missing_critical:
            status = 'GOOD'
            recommendation = 'Can use with minor verification'
        elif avg_confidence >= 0.60 or len(missing_critical) <= 1:
            status = 'FAIR'
            recommendation = 'Manual verification recommended'
        else:
            status = 'POOR'
            recommendation = 'Significant manual review required'
        
        return {
            'status': status,
            'overall_confidence': avg_confidence,
            'high_confidence_fields': high_conf_fields,
            'low_confidence_fields': low_conf_fields,
            'missing_critical_fields': list(missing_critical),
            'extracted_count': len(result.confidences),
            'recommendation': recommendation,
            'details': {
                'avg_confidence': f"{avg_confidence:.0%}",
                'high_conf_count': len(high_conf_fields),
                'low_conf_count': len(low_conf_fields),
                'all_critical_fields_present': len(missing_critical) == 0
            }
        }

    def _log_extraction_summary(self, result: AwbExtractionResult) -> None:
        """Log a summary of extraction results."""
        logger.info("=== EXTRACTION SUMMARY (v3 - Label-Based) ===")
        logger.info(f"AWB Number:         {result.data.awb_number}")
        logger.info(f"Shipper:            {result.data.shipper}")
        logger.info(f"Consignee:          {result.data.consignee}")
        logger.info(f"Agent:              {result.data.agent}")
        logger.info(f"Route:              {result.data.origin} → {result.data.destination}")
        logger.info(f"Pieces:             {result.data.pieces}")
        logger.info(f"Weight:             {result.data.weight} kg")
        logger.info(f"Goods Description:  {result.data.goods_description}")
        
        if result.confidences:
            avg_conf = sum(c.confidence for c in result.confidences) / len(result.confidences)
            logger.info(f"Average Confidence: {avg_conf:.0%}")
        
        logger.info("=" * 50)

    def _empty_result(self, text: str) -> AwbExtractionResult:
        """Create an empty extraction result (used on error)."""
        from .awb_schema import AwbData
        return AwbExtractionResult(
            data=AwbData(),
            confidences=[],
            raw_text=text
        )


# Convenient singleton-like access
_default_pipeline = None

def get_default_pipeline() -> IataAwbExtractionPipeline:
    """Get or create the default pipeline instance."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = IataAwbExtractionPipeline()
    return _default_pipeline


def extract_awb_quick(text: str) -> AwbExtractionResult:
    """
    Quick extraction using default pipeline.
    
    Example:
        result = extract_awb_quick(ocr_text)
        print(result.data.shipper)
    """
    pipeline = get_default_pipeline()
    return pipeline.extract(text, debug=False)


def extract_awb_debug(text: str) -> AwbExtractionResult:
    """
    Quick extraction with debug output.
    
    Example:
        result = extract_awb_debug(ocr_text)
    """
    pipeline = get_default_pipeline()
    return pipeline.extract(text, debug=True)
