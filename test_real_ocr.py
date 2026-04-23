#!/usr/bin/env python
"""Test v3 extraction with the real messy OCR document"""

from app.interpretation.iata_awb_extraction_pipeline_v3 import IataAwbExtractionPipeline

# Real OCR text from your document (messy layout)
REAL_OCR = r"""233\MXP|10166763 233-10166763

'Shipper's Name and Address Shipper's Account Number Not Negotiable
CEVA AIR&OCEAN Air Waybill
ITALY S.P.A. issued by MSC AIR S.P.A.

STRADA VECCHIA PAULLESE, 5/B E 5/A VIA GABRIELE D'ANNUNZIO 2
21010, VIZZOLA TICINO, ITALY

PANTIGLIATE MI 20048 IT
» | TE +3902906271 Eleonora LODA Copies 1, 2 and 3 of this Air Waybill are originals and have the same validity.

Consignee's Name and Address: Consignee's Account Number Itis agreed that the goods described herein are accepted in apparent good order and condition (except as
noted) for carriage SUBJECT TO THE CONDITIONS OF CONTRACT ON THE REVERSE HEREOF. ALL

CEVA HONG KONG GOODS MAY BE CARRIED BY ANY OTHER MEANS INCLUDING ROAD OR ANY OTHER CARRIER

LIMITED UNLESS SPECIFIC CONTRARY INSTRUCTIONS ARE GIVEN HEREON BY THE SHIPPER, AND
SHIPPER AGREES THAT THE SHIPMENT MAY BE CARRIED VIA INTERMEDIATE STOPPING

5 F MAGNET PLACE TOWER 1 PLACES WHICH THE CARRIER DEEMS APPROPRIATE. THE SHIPPER'S ATTENTION IS DRAWN TO

IER' A er may increase su
77-81 CONTAINER PORT ROAD KWAI CHUNG ici \RRIER'S LIMITATION OF LIABILITY. Shipper may ich

limitation of lability by declaring a higher value for carriage and paying a supplemental charge if required.

HONG KONG 00000 HK

Tssuing Carriers Agent Name and City

CEVA AIR&OCEAN S.P.A.
PANTIGLIATE

'Accounting Information

EAW

'Agent's IATA Code

38-4 7889/0015

'Airport of Departure (Addr. of First Carrier) and Requested Routing

Reference Number 'Optional Shipping Information

MALPENSA APT/MILANO C03623845
Routing and Destinalion [to Declared Value for Carriage Declared Value for Customs
NVD NCV
INSURANCE - I Carrer offers Insurance, and such Insurance is
requested in accordance with the conditions thereof, indicate amount to be
XXX insured in figures in box marked "amount of insurance",
Handling Information
scl
x
Gross ¥@] [Rate Class Chargeable
No. Of |. Weight » Weight Total 'Nature and Quantity of Goods
Pieces Commodity 'Charge otal (incl, Dimensions or Volume)
RCP. tem No.
1 806.91/K 4.50) 12375.00} |Consolidation as per attached list
239 PCS ON PMC10434CP
VOL 16.500 M3
239 SLAC
1 806.91 12375.00}
Prepaid Weight Charge Collect 7 [Other Charges
42375.00 MSC MISCELLANEOUS - DUE ISSUING CARRIER 0.03
Vatislon Chaeae AWC AIR WAYBILL/ SHIPMENT RECORD PREPARATION FEE 20.00
= MOC MISCELLANEOUS: - DUE ISSUING CARRIER 3.50
g ZBC GENERAL 137.50
Ss Tax
=
=
xt A
i Total Other Charges Due Agent [Shipper certifies that ihe parliculars on the face hereof are correct and that insofar as any part of the consignment
3 [contains dangerous goods, such part is properly described by name and is In proper condition for carriage by air according to
sg the applicable Dangerous Goods Regulations.
2 Total Other Charges Due Carrier
z|
3 161.03
3 SIMONE MARTINI
z % Signature of Shipper or his Agent
ie N "Total Prepaid Total Collect
a)
2 12536.03
© KT Gurrency Conversion Rates CC. Charges in Dest Currency /| 4 ATE
3 Executed on (date) at (place) Signature of Issuing Cartier or its Agent
= —
Che it Destinatic =Total Collect Charges /
For Caters use ony SS —— 233-10166763
at Destination

Original 3 - (for Shipper)
"""

def test_real_ocr():
    print("="*70)
    print("Testing v3 with REAL MESSY OCR Document")
    print("="*70)
    
    pipeline = IataAwbExtractionPipeline()
    result = pipeline.extract(REAL_OCR, debug=False)
    quality = pipeline.get_extraction_quality_report(result)
    
    print("\nEXTRACTED DATA:")
    print("-"*70)
    print(f"AWB:               {result.data.awb_number}")
    print(f"Shipper:           {result.data.shipper}")
    print(f"Consignee:         {result.data.consignee}")
    print(f"Agent:             {result.data.agent}")
    print(f"Origin:            {result.data.origin}")
    print(f"Destination:       {result.data.destination}")
    print(f"Pieces:            {result.data.pieces}")
    print(f"Gross Weight:      {result.data.weight} kg")
    print(f"Chargeable Weight: {result.data.chargeable_weight} kg")
    print(f"Goods:             {result.data.goods_description}")
    print(f"Flight:            {result.data.flight_no}")
    
    print("\nQUALITY ASSESSMENT:")
    print("-"*70)
    print(f"Status:            {quality['status']}")
    print(f"Confidence:        {quality['overall_confidence']:.0%}")
    
    print("\nCOMPARISON WITH EXPECTED:")
    print("-"*70)
    checks = {
        "AWB Number": (result.data.awb_number, "233-10166763"),
        "Origin": (result.data.origin, "MXP"),
        "Destination": (result.data.destination, "HKG"),
        "Pieces": (result.data.pieces, 239),
        "Gross Weight": (result.data.weight, 12375.0),
        "Chargeable Weight": (result.data.chargeable_weight, 2750.0),
    }
    
    for name, (actual, expected) in checks.items():
        match = "✓" if actual == expected else "✗"
        print(f"{match} {name}: {actual} (expected: {expected})")

if __name__ == '__main__':
    test_real_ocr()
