"""
AWB Extraction Pipeline v2 - Integration example

Shows how to use the new section-aware parsing agent.
This replaces the old hybrid extractor with a more intelligent approach.

Usage:
    extractor = AwbExtractionPipelineV2(llm_provider)
    result = extractor.extract(ocr_text)
    result = extractor.extract(ocr_text, debug=True)  # With detailed debug info
"""

from typing import Dict, Any, Optional
import logging

from .awb_parsing_agent import AwbParsingAgent
from .awb_schema import AwbExtractionResult

logger = logging.getLogger(__name__)


class AwbExtractionPipelineV2:
    """
    Enhanced AWB extraction pipeline using intelligent section analysis.
    
    This pipeline replaces the previous simple hybrid approach with a more
    sophisticated multi-layer system that:
    
    1. Analyzes document structure (sections)
    2. Extracts structured fields with high confidence (rule-based)
    3. Extracts semantic fields with section context (LLM)
    4. Validates all extracted data
    5. Intelligently merges results
    6. Tracks confidence and quality metrics
    """

    def __init__(self, llm_provider):
        """
        Initialize the extraction pipeline.
        
        Args:
            llm_provider: LLM provider instance (e.g., Phi3LocalProvider, CohereLLMProvider)
        """
        self.llm_provider = llm_provider
        self.agent = AwbParsingAgent(llm_provider)

    def extract(
        self,
        text: str,
        debug: bool = False
    ) -> AwbExtractionResult:
        """
        Extract AWB data from OCR-extracted text using intelligent pipeline.
        
        Args:
            text: OCR-extracted AWB document text
            debug: If True, print detailed debug information about each extraction layer
            
        Returns:
            AwbExtractionResult containing:
            - data: AwbData with all extracted fields
            - confidences: List of confidence scores per field
            - raw_text: Original OCR text for reference
            
        Example:
            >>> extractor = AwbExtractionPipelineV2(phi3_provider)
            >>> result = extractor.extract(ocr_text, debug=True)
            >>> print(f"AWB: {result.data.awb_number}")
            >>> print(f"Overall confidence: {result.data}")
            >>> for conf in result.confidences:
            ...     print(f"  {conf.field}: {conf.confidence:.0%}")
        """
        try:
            if debug:
                logger.info("Starting AWB extraction pipeline (v2 - section-aware)")
                logger.info(f"OCR text length: {len(text)} characters")
            
            # Run the intelligent parsing agent
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
        texts: list[str],
        debug: bool = False
    ) -> list[AwbExtractionResult]:
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
        logger.info("=== EXTRACTION SUMMARY ===")
        logger.info(f"AWB Number: {result.data.awb_number}")
        logger.info(f"Shipper: {result.data.shipper}")
        logger.info(f"Consignee: {result.data.consignee}")
        logger.info(f"Origin -> Destination: {result.data.origin} -> {result.data.destination}")
        logger.info(f"Pieces: {result.data.pieces}, Weight: {result.data.weight} kg")
        
        if result.confidences:
            avg_conf = sum(c.confidence for c in result.confidences) / len(result.confidences)
            logger.info(f"Average Confidence: {avg_conf:.0%}")
        
        logger.info("========================")

    def _empty_result(self, text: str) -> AwbExtractionResult:
        """Create an empty extraction result (used on error)."""
        from .awb_schema import AwbData
        return AwbExtractionResult(
            data=AwbData(),
            confidences=[],
            raw_text=text
        )


# Compatibility wrapper for existing code
class AwbExtractionPipeline(AwbExtractionPipelineV2):
    """
    Backward-compatible wrapper for the new pipeline.
    Can be used as a drop-in replacement for the old hybrid extractor.
    """
    
    def extract_to_dict(self, text: str, debug: bool = False) -> Dict[str, Any]:
        """
        Extract and return results as a simple dictionary (for compatibility).
        
        Returns the same format as old awb_llm_extractor.extract()
        """
        result = self.extract(text, debug=debug)
        
        return {
            'awb_number': result.data.awb_number,
            'shipper': result.data.shipper,
            'consignee': result.data.consignee,
            'agent': result.data.agent,
            'origin': result.data.origin,
            'destination': result.data.destination,
            'pieces': result.data.pieces,
            'weight': result.data.weight,
            'goods_description': result.data.goods_description,
            'flight_number': result.data.flight_no,
            'flight_date': result.data.flight_date,
            'confidences': {c.field: c.confidence for c in result.confidences}
        }
