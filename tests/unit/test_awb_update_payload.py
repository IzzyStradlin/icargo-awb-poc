from app.ui.pages.pdf_upload import _build_awb_update_payload


def test_awb_payload_empties_zero_value_uld_section():
    payload = _build_awb_update_payload(
        base_awb={
            "uld_details": [{"uld_number": "", "pieces": 0, "weight": 0}],
        },
        extracted_mawb={},
        selected_fields=set(),
        edited_values={},
        awb_code="001-12345678",
    )

    assert payload["uld_details"] == []


def test_awb_payload_preserves_populated_uld_section():
    payload = _build_awb_update_payload(
        base_awb={
            "uld_details": [{"uld_number": "AKE12345XX", "pieces": 0, "weight": 0}],
        },
        extracted_mawb={},
        selected_fields=set(),
        edited_values={},
        awb_code="001-12345678",
    )

    assert payload["uld_details"] == [{"uld_number": "AKE12345XX", "pieces": 0, "weight": 0}]