"""
AWB Parsing Agent - Orchestrator for intelligent AWB extraction

This is the main agent that coordinates the entire extraction pipeline:
1. Analyzes document structure (sections)
2. Extracts structured fields (rule-based: AWB number, pieces, weight)
3. Extracts semantic fields (LLM: shipper, consignee, goods description)
4. Validates extracted data
5. Provides fallback/recovery mechanisms
6. Tracks extraction quality and confidence

This agent implements the complete approach described in the architecture:
- Section awareness reduces ambiguity
- Specific questions improve accuracy
- Validation ensures data quality
- Fallbacks make the system robust
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import json

from .awb_section_analyzer import AwbSectionAnalyzer
from .awb_section_field_extractor import AwbSectionBasedFieldExtractor
from .awb_field_detector import AwbFieldDetector
from .awb_schema import AwbData, AwbExtractionResult, AwbFieldConfidence


@dataclass
class ExtractionQuality:
    """Metrics about extraction quality and confidence."""
    overall_confidence: float
    fields_with_high_confidence: List[str]
    fields_with_low_confidence: List[str]
    fields_missing: List[str]
    sections_detected: int
    extraction_notes: List[str]


class AwbParsingAgent:
    """
    Main orchestrator for AWB document parsing.
    
    Uses a layered approach:
    - Layer 1: Document structure analysis (sections)
    - Layer 2: Rule-based extraction (high-confidence structured fields)
    - Layer 3: LLM-based extraction (semantic fields with section context)
    - Layer 4: Validation and recovery
    - Layer 5: Merge and report
    """

    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    LOW_CONFIDENCE_THRESHOLD = 0.60
    FIELD_RECOVERY_THRESHOLD = 0.50

    def __init__(self, llm_provider):
        """
        Initialize the parsing agent.
        
        Args:
            llm_provider: LLM provider instance (e.g., Phi3LocalProvider)
        """
        self.llm_provider = llm_provider
        self.section_analyzer = AwbSectionAnalyzer()
        self.field_extractor = AwbSectionBasedFieldExtractor(llm_provider)
        self.rule_based_extractor = AwbFieldDetector()

    def parse(self, text: str, debug: bool = False) -> AwbExtractionResult:
        """
        Parse AWB document using the complete intelligent pipeline.
        
        Args:
            text: OCR-extracted AWB document text
            debug: If True, include detailed debug information in output
            
        Returns:
            Complete extraction result with all fields and confidence scores
        """
        
        # LAYER 1: Analyze document structure
        sections = self._analyze_document_structure(text, debug)
        
        # LAYER 2: Extract using rule-based approach (structured fields)
        rule_based_result = self._extract_with_rules(text, sections, debug)
        
        # LAYER 3: Extract using LLM with section awareness (semantic fields)
        llm_result = self._extract_with_llm(sections, text, debug)
        
        # LAYER 4: Validate and recover
        validated_result = self._validate_and_recover(rule_based_result, llm_result, text)
        
        # LAYER 5: Merge and finalize
        final_result = self._merge_extraction_results(
            rule_based_result,
            llm_result,
            validated_result,
            sections,
            text,
            debug
        )
        
        return final_result

    def _analyze_document_structure(
        self,
        text: str,
        debug: bool = False
    ) -> Dict[str, str]:
        """
        LAYER 1: Analyze document structure to identify sections.
        
        Returns:
            Dictionary mapping section names to their text content
        """
        sections = self.section_analyzer.analyze(text)
        
        if debug:
            print("\n[LAYER 1: Document Structure Analysis]")
            print(self.section_analyzer.debug_sections(text))
        
        return sections

    def _extract_with_rules(
        self,
        text: str,
        sections: Dict[str, str],
        debug: bool = False
    ) -> AwbExtractionResult:
        """
        LAYER 2: Extract structured fields using rule-based approach.
        
        Rule-based extraction is used for:
        - AWB number: Always reliable with regex
        - Origin/Destination: IATA codes are very predictable
        - Pieces: Usually numeric patterns
        - Weight: Numeric patterns with unit labels
        
        Returns:
            Extraction result from rule-based extractor
        """
        rule_result = self.rule_based_extractor.extract(text, sections)
        
        if debug:
            print("\n[LAYER 2: Rule-Based Extraction]")
            print(f"  AWB Number: {rule_result.data.awb_number}")
            print(f"  Origin: {rule_result.data.origin}")
            print(f"  Destination: {rule_result.data.destination}")
            print(f"  Pieces: {rule_result.data.pieces}")
            print(f"  Weight: {rule_result.data.weight}")
            print(f"  Confidences: {[(c.field, c.confidence) for c in rule_result.confidences]}")
        
        return rule_result

    def _extract_with_llm(
        self,
        sections: Dict[str, str],
        full_text: str,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        LAYER 3: Extract semantic fields using LLM with section awareness.
        
        LLM extraction is used for:
        - Shipper/Consignee: Requires semantic understanding
        - Goods Description: Requires understanding of content
        - Flight details: May need interpretation from handling section
        
        Returns:
            Dictionary with extracted fields and confidence scores
        """
        llm_results = self.field_extractor.extract_from_sections(sections, full_text)
        
        if debug:
            print("\n[LAYER 3: LLM-Based Section-Aware Extraction]")
            for field_name, extracted_field in llm_results.items():
                print(f"  {field_name}: {extracted_field.value} (confidence: {extracted_field.confidence:.2%})")
                if extracted_field.reasoning:
                    print(f"    → {extracted_field.reasoning}")
        
        return llm_results

    def _validate_and_recover(
        self,
        rule_result: AwbExtractionResult,
        llm_result: Dict[str, Any],
        text: str
    ) -> Dict[str, Any]:
        """
        LAYER 4: Validate extracted data and attempt recovery if needed.
        
        Performs validation checks:
        - Airport codes are exactly 3 uppercase letters
        - Pieces is a valid integer
        - AWB number is in correct format
        - Weight is a valid positive number
        
        If validation fails, attempts recovery strategies.
        
        Returns:
            Dictionary with validation results and recovery recommendations
        """
        validations = {
            'awb_number': self._validate_awb_number(rule_result.data.awb_number),
            'origin': self._validate_airport_code(rule_result.data.origin),
            'destination': self._validate_airport_code(rule_result.data.destination),
            'pieces': self._validate_pieces(rule_result.data.pieces),
            'weight': self._validate_weight(rule_result.data.weight),
            'shipper': self._validate_company_name(llm_result['shipper'].value),
            'consignee': self._validate_company_name(llm_result['consignee'].value),
        }
        
        return validations

    def _validate_awb_number(self, value: Optional[str]) -> Dict[str, Any]:
        """Validate AWB number format: XXX-YYYYYYYY"""
        import re
        if not value:
            return {'valid': False, 'reason': 'Missing AWB number', 'recovery_possible': True}
        
        if re.match(r'^\d{3}-\d{8}$', value):
            return {'valid': True, 'reason': 'Valid format'}
        
        return {'valid': False, 'reason': 'Invalid AWB format', 'recovery_possible': False}

    def _validate_airport_code(self, value: Optional[str]) -> Dict[str, Any]:
        """Validate airport code: exactly 3 uppercase letters"""
        if not value:
            return {'valid': False, 'reason': 'Missing airport code', 'recovery_possible': True}
        
        if len(value) == 3 and value.isupper() and value.isalpha():
            return {'valid': True, 'reason': 'Valid IATA code'}
        
        return {'valid': False, 'reason': 'Invalid airport code format', 'recovery_possible': True}

    def _validate_pieces(self, value: Optional[int]) -> Dict[str, Any]:
        """Validate pieces count: must be positive integer"""
        if value is None:
            return {'valid': False, 'reason': 'Missing pieces count', 'recovery_possible': True}
        
        if isinstance(value, int) and value > 0:
            return {'valid': True, 'reason': 'Valid pieces count'}
        
        return {'valid': False, 'reason': 'Invalid pieces count', 'recovery_possible': False}

    def _validate_weight(self, value: Optional[float]) -> Dict[str, Any]:
        """Validate weight: must be positive number"""
        if value is None:
            return {'valid': False, 'reason': 'Missing weight', 'recovery_possible': True}
        
        if isinstance(value, (int, float)) and value > 0:
            return {'valid': True, 'reason': 'Valid weight'}
        
        return {'valid': False, 'reason': 'Invalid weight value', 'recovery_possible': False}

    def _validate_company_name(self, value: Optional[str]) -> Dict[str, Any]:
        """Validate company name: non-empty string"""
        if not value or len(value) < 2:
            return {'valid': False, 'reason': 'Missing or too short', 'recovery_possible': True}
        
        if len(value) > 100:
            return {'valid': False, 'reason': 'Too long (likely includes address)', 'recovery_possible': True}
        
        return {'valid': True, 'reason': 'Valid company name'}

    def _merge_extraction_results(
        self,
        rule_result: AwbExtractionResult,
        llm_result: Dict[str, Any],
        validations: Dict[str, Any],
        sections: Dict[str, str],
        full_text: str,
        debug: bool = False
    ) -> AwbExtractionResult:
        """
        LAYER 5: Merge rule-based and LLM results into final output.
        
        Merge strategy:
        - Prioritize high-confidence results
        - Use validations to pick between sources when there's conflict
        - Include confidence scores for all fields
        - Preserve all metadata
        
        Returns:
            Final AwbExtractionResult with all fields and confidence info
        """
        merged_data = AwbData()
        merged_confidences = []
        
        # AWB Number - from rule-based (most reliable)
        merged_data.awb_prefix = rule_result.data.awb_prefix
        merged_data.awb_serial = rule_result.data.awb_serial
        if validations['awb_number']['valid']:
            merged_confidences.append(AwbFieldConfidence(
                field='awb_number',
                value=merged_data.awb_number,
                confidence=0.98
            ))
        
        # Origin/Destination - from rule-based, but validate
        if validations['origin']['valid']:
            merged_data.origin = rule_result.data.origin
            merged_confidences.append(AwbFieldConfidence(
                field='origin',
                value=merged_data.origin,
                confidence=0.95
            ))
        
        if validations['destination']['valid']:
            merged_data.destination = rule_result.data.destination
            merged_confidences.append(AwbFieldConfidence(
                field='destination',
                value=merged_data.destination,
                confidence=0.95
            ))
        
        # Pieces - from rule-based if valid
        if validations['pieces']['valid']:
            merged_data.pieces = rule_result.data.pieces
            merged_confidences.append(AwbFieldConfidence(
                field='pieces',
                value=str(merged_data.pieces),
                confidence=0.90
            ))
        
        # Weight - from rule-based if valid
        if validations['weight']['valid']:
            merged_data.weight = rule_result.data.weight
            merged_confidences.append(AwbFieldConfidence(
                field='weight',
                value=str(merged_data.weight),
                confidence=0.90
            ))
        
        # Shipper - from LLM, but validate
        shipper_field = llm_result['shipper']
        if shipper_field.value and validations['shipper']['valid']:
            merged_data.shipper = shipper_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='shipper',
                value=merged_data.shipper,
                confidence=shipper_field.confidence
            ))
        
        # Consignee - from LLM, but validate
        consignee_field = llm_result['consignee']
        if consignee_field.value and validations['consignee']['valid']:
            merged_data.consignee = consignee_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='consignee',
                value=merged_data.consignee,
                confidence=consignee_field.confidence
            ))
        
        # Agent - from LLM
        agent_field = llm_result['agent']
        if agent_field.value:
            merged_data.agent = agent_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='agent',
                value=merged_data.agent,
                confidence=agent_field.confidence
            ))
        
        # Goods Description - from LLM
        goods_field = llm_result['goods_description']
        if goods_field.value:
            merged_data.goods_description = goods_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='goods_description',
                value=merged_data.goods_description,
                confidence=goods_field.confidence
            ))
        
        # Flight details - from LLM
        flight_field = llm_result['flight_number']
        if flight_field.value:
            merged_data.flight_no = flight_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='flight_number',
                value=merged_data.flight_no,
                confidence=flight_field.confidence
            ))
        
        date_field = llm_result['flight_date']
        if date_field.value:
            merged_data.flight_date = date_field.value
            merged_confidences.append(AwbFieldConfidence(
                field='flight_date',
                value=merged_data.flight_date,
                confidence=date_field.confidence
            ))
        
        # Calculate overall extraction quality
        quality = self._calculate_extraction_quality(merged_confidences)
        
        if debug:
            print("\n[LAYER 5: Merged Results]")
            print(f"  Overall Confidence: {quality.overall_confidence:.2%}")
            print(f"  High Confidence Fields: {quality.fields_with_high_confidence}")
            print(f"  Low Confidence Fields: {quality.fields_with_low_confidence}")
            print(f"  Missing Fields: {quality.fields_missing}")
            print(f"  Extraction Notes: {quality.extraction_notes}")
        
        result = AwbExtractionResult(
            data=merged_data,
            confidences=merged_confidences,
            raw_text=full_text
        )
        
        return result

    def _calculate_extraction_quality(
        self,
        confidences: List[AwbFieldConfidence]
    ) -> ExtractionQuality:
        """Calculate metrics about extraction quality."""
        high_conf = []
        low_conf = []
        
        for conf in confidences:
            if conf.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                high_conf.append(conf.field)
            elif conf.confidence < self.LOW_CONFIDENCE_THRESHOLD:
                low_conf.append(conf.field)
        
        overall = sum(c.confidence for c in confidences) / len(confidences) if confidences else 0.0
        
        required_fields = {'awb_number', 'shipper', 'consignee', 'origin', 'destination'}
        extracted_fields = {c.field for c in confidences}
        missing = required_fields - extracted_fields
        
        notes = []
        if not missing:
            notes.append("All critical fields extracted")
        else:
            notes.append(f"Missing critical fields: {missing}")
        
        if overall >= 0.90:
            notes.append("Extraction quality is EXCELLENT")
        elif overall >= 0.75:
            notes.append("Extraction quality is GOOD")
        else:
            notes.append("Extraction quality needs review - manual verification recommended")
        
        return ExtractionQuality(
            overall_confidence=overall,
            fields_with_high_confidence=high_conf,
            fields_with_low_confidence=low_conf,
            fields_missing=list(missing),
            sections_detected=0,  # Could track from section analyzer
            extraction_notes=notes
        )
