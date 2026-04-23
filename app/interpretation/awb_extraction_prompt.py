"""
AWB Extraction Prompt Template
Describes the IATA AWB structure to LLM for better extraction
"""

AWB_STRUCTURE_PROMPT = """You are an expert Air Waybill (AWB) parser trained on IATA standards and logistics.

## IATA Air Waybill (AWB) Structure - DETAILED FIELD GUIDE:

### AWB NUMBER (MANDATORY)
- Format: XXX-YYYYYYYY (3-digit airline prefix + dash + 8-digit serial number)
- Examples: 233-12345678, 639-98765432, 001-55555555
- Location: Usually top-right corner of the form
- Look for: patterns like "233-", "639-", or any 3-digit code followed by 8 digits

### SHIPPER (Required)
- The company/person SENDING the goods
- Typically in Box 1 or top-left section
- Includes company name followed by full address
- Extract ONLY the company name (not address)
- Examples: "DHL Supply Chain Italy", "Ferrari S.p.A.", "Pirelli Group"

### CONSIGNEE (Required)
- The company/person RECEIVING the goods
- Typically in Box 2 or middle-left section
- Includes company name followed by full address
- Extract ONLY the company name (not address)
- Examples: "BMW Munich", "Porsche Logistics", "Mercedes Distribution"

### AGENT (Optional)
- Freight forwarder or customs broker handling the shipment
- Often same as shipper or in Box 4
- Company name only
- Examples: "DHL", "FedEx", "UPS"

### ORIGIN - AIRPORT OF DEPARTURE (Required)
- 3-letter IATA airport code where shipment departs FROM
- MUST be exactly 3 uppercase letters
- Common European codes: MXP (Milan), FCO (Rome), VCE (Venice), BGY (Bergamo), CGN (Cologne), CDG (Paris)
- Look for: words "ORIGIN", "DEPARTURE", "FROM", or codes near shipper location

### DESTINATION - AIRPORT OF ARRIVAL (Required)
- 3-letter IATA airport code where shipment arrives TO
- MUST be exactly 3 uppercase letters
- Common European codes: MXP, FCO, VCE, BGY, CDG, AMS (Amsterdam), TXL (Berlin)
- Look for: words "DESTINATION", "ARRIVAL", "TO", or codes near consignee location

### PIECES (Optional)
- Number of packages/pallets in the shipment
- MUST be an integer (whole number)
- Look for: labels like "NO. OF PIECES", "PCS", "PIECES", "PKG", "TOTAL"
- Examples: 1, 5, 12, 100

### WEIGHT (Optional)
- Gross weight of entire shipment in KILOGRAMS
- Can be decimal number (may use comma as decimal separator in European documents)
- Examples: 500, 1500.5, 2000 (if "1500,5" in text, convert to 1500.5)
- Look for: labels like "GROSS WEIGHT", "WT", "KG", "GWT"

### FLIGHT NUMBER & DATE (Conditional)
- Flight number: airline code + numeric flight number (e.g., CP137, LH2054, BA285)
- Flight date: date the flight departs (YYYY-MM-DD format)
- Look for: "FLIGHT", "FLIGHT NO", "DEPARTURE", "DATE OF FLIGHT"
- May be optional for consolidated shipments

### GOODS DESCRIPTION (Optional)
- What is being shipped
- Look for: "DESCRIPTION OF GOODS", "CONTENTS", "SAID TO CONTAIN"
- Extract a short description only
- Examples: "Electronic components", "Auto parts", "Fashion items"

## CRITICAL EXTRACTION RULES:
1. **Airport codes MUST be 3 uppercase letters** - reject anything else
2. **NEVER invent codes** - if you can't find clear 3-letter codes, return null
3. **Company names**: Extract clean names without address details or legal text
4. **Numbers**: Pieces must be integers, Weight must be numeric (handle commas as decimals)
5. **AWB format**: MUST be XXX-YYYYYYYY or null - no exceptions
6. **If uncertain**: Return null, don't guess

## COMMON OCR ERRORS TO HANDLE:
- O (letter) confused with 0 (zero) in AWB numbers
- I (letter) confused with 1 (one) in AWB numbers
- l (lowercase L) confused with 1 (one)
- 5 confused with S
- Special characters or boxes around fields
- Extra spaces or line breaks within field values

## OUTPUT RULES:
- Return ONLY valid JSON (no markdown, no explanations)
- All null fields must be null (not empty string "", not "null" string)
- No decorative text or comments

Given the following OCR text from an Air Waybill, extract fields with high precision:
"""

# Compact version for token-limited models
AWB_STRUCTURE_PROMPT_COMPACT = """Extract AWB fields:
- AWB_NUMBER: XXX-YYYYYYYY format (3 digits - 8 digits)
- SHIPPER: Company name, Box 1 top-left
- SHIPPER_ADDRESS: Full address of shipper (street, city, country)
- CONSIGNEE: Company name, Box 2 middle-left  
- CONSIGNEE_ADDRESS: Full address of consignee (street, city, country)
- AGENT: Handler/forwarder company
- AGENT_ADDRESS: Full address of agent/handler
- ORIGIN: 3-letter IATA airport code FROM shipper
- DESTINATION: 3-letter IATA airport code TO consignee
- PIECES: Integer count
- WEIGHT: Number in KG
- FLIGHT_NUMBER: Airline code + numbers (e.g. CP137)
- FLIGHT_DATE: Date format
- GOODS_DESCRIPTION: What's being shipped

CRITICAL:
- Airport codes = exactly 3 uppercase letters ONLY (MXP, FCO, VCE, BGY, CDG)
- Addresses should be complete but concise (street, city, country code)
- If not 100% sure, return null
- Return valid JSON only
"""

def get_extraction_prompt(ocr_text: str) -> str:
    """Build full extraction prompt with OCR text"""
    return AWB_STRUCTURE_PROMPT + f"""

HERE IS THE ACTUAL OCR TEXT FROM THE AIR WAYBILL:

```
{ocr_text}
```

INSTRUCTIONS FOR THIS SPECIFIC DOCUMENT:
1. Search for airport IATA codes (3 uppercase letters like MXP, FCO, BGY, VCE)
2. Look for company names near shipper and consignee boxes
3. Find numeric values for pieces and weight
4. Look for flight codes (airline prefix + numbers like CP137, BA285, LH2054)
5. Find date patterns that could be flight dates

Return ONLY this JSON (no markdown, no explanation, no extra text):
{{
    "awb_number": "XXX-YYYYYYYY or null",
    "shipper": "Company name or null",
    "shipper_address": "Full address or null",
    "consignee": "Company name or null",
    "consignee_address": "Full address or null",
    "agent": "Agency name or null",
    "agent_address": "Full address or null",
    "origin": "3-letter IATA code or null",
    "destination": "3-letter IATA code or null",
    "pieces": "Integer or null",
    "weight": "Decimal number or null",
    "flight_number": "Flight code like CP137 or null",
    "flight_date": "YYYY-MM-DD or null",
    "goods_description": "What is being shipped or null"
}}

CRITICAL: If you're not 100% sure about a field, return null. Never invent values.
"""

def get_extraction_prompt_with_fixed_awb(ocr_text: str, awb_number: str, prefix_code: str = "233") -> str:
    """
    Build extraction prompt where AWB number is FIXED (extracted via regex).
    LLM should NOT modify it, only extract other fields.
    
    Args:
        ocr_text: OCR text from document
        awb_number: Pre-extracted AWB number (e.g., "233-10147701")
        prefix_code: Airline prefix (e.g., "233" for MSC AIR)
    
    Returns:
        Full prompt with fixed AWB
    """
    return f"""Extract AWB fields for this MSC AIR (prefix {prefix_code}) shipment.

THE AWB NUMBER IS ALREADY EXTRACTED AND FIXED: {awb_number}
DO NOT EXTRACT OR MODIFY THE AWB_NUMBER FIELD - USE THE VALUE PROVIDED ABOVE.

EXTRACT ONLY THESE FIELDS:
- SHIPPER: Company name from Box 1 (top-left). Do NOT include carrier name (e.g. "MSC AIR", "Air Waybill", "Issued by" text belongs to the carrier column on the right — ignore it).
- SHIPPER_ADDRESS: Full address of shipper ONLY (street, city, ZIP, country). Do NOT include the carrier's address which appears on the right column of the same lines.
- CONSIGNEE: Company name from Box 2 (middle-left). Include full name with legal suffix (e.g. LIMITED, LTD).
- CONSIGNEE_ADDRESS: Full address of consignee (street, city, country). Include street name like "CONTAINER PORT ROAD" if present.
- AGENT: Handler/forwarder company name (from "Issuing Carrier's Agent" field)
- AGENT_ADDRESS: Full address of agent/handler
- ORIGIN: 3-letter IATA airport code FROM shipper
- DESTINATION: 3-letter IATA airport code TO consignee
- PIECES: Integer count — use ONLY the first column of the cargo table row (the number before the gross weight). Do NOT use piece counts from goods description (e.g. "239 PCS ON PMC..." is NOT the pieces field).
- WEIGHT: Gross weight in KG — the number immediately followed by /K or /KG in the cargo table (e.g. "806.91/K" → 806.91)
- CHARGEABLE_WEIGHT: Billing weight in KG — the number AFTER gross weight and BEFORE the rate in the cargo table row. In a row "1  806.91/K  2750.0  4.50)  12375.00}}", chargeable weight is 2750.0. NEVER the last number.
- RATE: Rate per kg — small decimal, always less than 1000 (e.g. 4.50)
- TOTAL_CHARGE: Total freight charge — the LAST number in the cargo data row, often followed by "}}" (e.g. 12375.00). Never equal to chargeable_weight.
- FLIGHT_NUMBER: Airline code + numbers (e.g. CP137) — from "Requested Flight/Date" field ONLY
- FLIGHT_DATE: Date — from "Requested Flight/Date" field ONLY
- GOODS_DESCRIPTION: What is being shipped

CRITICAL RULES:
- Airport codes = exactly 3 uppercase letters ONLY (MXP, FCO, VCE, BGY, CDG, HKG, etc.)
- Addresses should be complete but concise
- If not 100% sure about a field, return null
- NEVER modify or change the AWB_NUMBER - use: {awb_number}
- Return valid JSON only

HERE IS THE OCR TEXT:

```
{ocr_text}
```

Return ONLY this JSON (no markdown, no explanation):
{{
    "awb_number": "{awb_number}",
    "shipper": "Company name or null",
    "shipper_address": "Full address or null",
    "consignee": "Company name or null",
    "consignee_address": "Full address or null",
    "agent": "Agency name or null",
    "agent_address": "Full address or null",
    "origin": "3-letter IATA code or null",
    "destination": "3-letter IATA code or null",
    "pieces": "Integer or null",
    "weight": "Decimal number or null",
    "chargeable_weight": "Decimal number or null",
    "rate": "Decimal number or null",
    "total_charge": "Decimal number or null",
    "flight_number": "Flight code or null",
    "flight_date": "YYYY-MM-DD or null",
    "goods_description": "What is being shipped or null"
}}
"""
